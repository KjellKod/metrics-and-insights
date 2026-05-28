import argparse
import csv
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

import requests
from requests import RequestException

# pylint: disable=import-error
from cycle_time import business_time_spent_in_seconds
from jira_utils import (
    calculate_total_time_in_status,
    get_common_parser,
    get_issue_created_month_key,
    get_team_or_project_unknown,
    get_tickets_from_jira,
    is_month_key_in_date_range,
    parse_common_arguments,
    print_env_variables,
    verbose_print,
)


HOURS_TO_DAYS = 8
SECONDS_TO_HOURS = 3600
MISSING_IN_PROGRESS = "missing in-progress"
NO_NEXT_STATUS = "no next status after in-progress"


@dataclass(frozen=True)
class DevelopmentWindowResult:
    issue_id: str
    month_key: str
    business_seconds: float | None = None
    reason: str | None = None


@dataclass
class MonthlyDevelopmentTimeBucket:
    development_times: list[tuple[float, str]] = field(default_factory=list)
    skipped_missing_in_progress: int = 0
    skipped_no_next_status: int = 0


def parse_issue_types(value: str) -> list[str]:
    issue_types = [issue_type.strip() for issue_type in value.split(",") if issue_type.strip()]
    if not issue_types:
        raise argparse.ArgumentTypeError("--issue-types must include at least one issue type")
    return issue_types


def get_jira_issue_type_names() -> list[str]:
    jira_link = os.environ.get("JIRA_LINK")
    user_email = os.environ.get("USER_EMAIL")
    api_key = os.environ.get("JIRA_API_KEY")

    if not all([jira_link, user_email, api_key]):
        raise ValueError("Missing required environment variables for Jira issue type validation")

    api_issue_types_url = f"{jira_link.rstrip('/')}/rest/api/3/issuetype"
    try:
        response = requests.get(
            api_issue_types_url,
            auth=(user_email, api_key),
            headers={"Accept": "application/json"},
            timeout=30,
        )
    except RequestException as exc:
        raise ValueError(f"Unable to validate Jira issue types: {exc}") from exc

    if response.status_code != 200:
        print(f"ERROR: Issue type validation failed with status {response.status_code}")
        print(f"URL: {response.url}")
        print(f"Response: {response.text[:500]}")

    try:
        response.raise_for_status()
    except RequestException as exc:
        raise ValueError(f"Unable to validate Jira issue types: {exc}") from exc

    data = response.json()
    if not isinstance(data, list):
        raise ValueError(f"Unexpected issue type response format: expected list, got {type(data).__name__}")

    return [
        issue_type["name"]
        for issue_type in data
        if isinstance(issue_type, dict) and isinstance(issue_type.get("name"), str)
    ]


def validate_issue_types_exist(issue_types: list[str]) -> None:
    available_issue_types = get_jira_issue_type_names()
    available_by_name = {issue_type.casefold(): issue_type for issue_type in available_issue_types}
    missing_issue_types = [issue_type for issue_type in issue_types if issue_type.casefold() not in available_by_name]

    if missing_issue_types:
        available_display = ", ".join(sorted(available_issue_types, key=str.casefold))
        missing_display = ", ".join(missing_issue_types)
        raise ValueError(f"Unknown Jira issue type(s): {missing_display}. Available issue types: {available_display}")

    print(f"Validated Jira issue types: {', '.join(issue_types)}")


def parse_projects_from_env() -> list[str]:
    raw_projects = os.environ.get("JIRA_PROJECTS", "")
    projects = [project.strip() for project in raw_projects.split(",") if project.strip()]
    if not projects:
        raise ValueError("JIRA_PROJECTS must be set to a comma-separated list of Jira project keys")
    return projects


def quote_jql_values(values: list[str]) -> str:
    quoted_values = []
    for value in values:
        escaped_value = value.replace("\\", "\\\\").replace('"', '\\"')
        quoted_values.append(f'"{escaped_value}"')
    return ", ".join(quoted_values)


def build_development_time_jql(
    projects: list[str],
    issue_types: list[str],
    start_date: str,
    end_date: str,
) -> str:
    return (
        f"project in ({', '.join(projects)}) "
        f'AND status CHANGED FROM "In Progress" DURING ("{start_date}", "{end_date}") '
        'AND status != "In Progress" '
        f"AND issueType in ({quote_jql_values(issue_types)}) "
        "ORDER BY updated ASC"
    )


def resolve_reporting_date_range(
    args: argparse.Namespace,
    current_year: int | None = None,
) -> tuple[str, str]:
    date_ranges = resolve_reporting_date_ranges(args, current_year)
    return date_ranges[0][0], date_ranges[-1][1]


def resolve_reporting_date_ranges(
    args: argparse.Namespace,
    current_year: int | None = None,
) -> list[tuple[str, str]]:
    has_year_range = args.start_year is not None or args.end_year is not None
    if args.year is not None and has_year_range:
        raise ValueError("--year cannot be combined with --start-year or --end-year")

    if has_year_range:
        if args.start_year is None or args.end_year is None:
            raise ValueError("--start-year and --end-year must be provided together")
        if args.start_year > args.end_year:
            raise ValueError("--start-year must be less than or equal to --end-year")
        return [(f"{year}-01-01", f"{year}-12-31") for year in range(args.start_year, args.end_year + 1)]

    target_year = args.year or current_year or datetime.now().year
    return [(f"{target_year}-01-01", f"{target_year}-12-31")]


def calculate_total_development_window(issue: object) -> DevelopmentWindowResult:
    time_in_status = calculate_total_time_in_status(
        issue,
        "In Progress",
        business_time_spent_in_seconds,
    )

    if time_in_status.completed_intervals and time_in_status.last_exit_timestamp:
        return DevelopmentWindowResult(
            issue_id=time_in_status.issue_id,
            month_key=time_in_status.last_exit_timestamp.strftime("%Y-%m"),
            business_seconds=time_in_status.total_seconds,
        )

    if time_in_status.saw_status and time_in_status.open_start_timestamp:
        return DevelopmentWindowResult(
            issue_id=time_in_status.issue_id,
            month_key=time_in_status.open_start_timestamp.strftime("%Y-%m"),
            reason=NO_NEXT_STATUS,
        )

    return DevelopmentWindowResult(
        issue_id=time_in_status.issue_id,
        month_key=get_issue_created_month_key(issue),
        reason=MISSING_IN_PROGRESS,
    )


def calculate_percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return sorted_values[0]

    rank = (len(sorted_values) - 1) * percentile
    lower_index = int(rank)
    upper_index = min(lower_index + 1, len(sorted_values) - 1)
    lower_value = sorted_values[lower_index]
    upper_value = sorted_values[upper_index]
    weight = rank - lower_index
    return lower_value + ((upper_value - lower_value) * weight)


def _add_result_to_bucket(
    bucket: MonthlyDevelopmentTimeBucket,
    result: DevelopmentWindowResult,
) -> None:
    if result.reason == MISSING_IN_PROGRESS:
        bucket.skipped_missing_in_progress += 1
    elif result.reason == NO_NEXT_STATUS:
        bucket.skipped_no_next_status += 1
    elif result.business_seconds is not None:
        bucket.development_times.append((result.business_seconds, result.issue_id))


def _record_development_time_result(
    metrics_by_team_month: defaultdict[str, defaultdict[str, MonthlyDevelopmentTimeBucket]],
    team: str,
    result: DevelopmentWindowResult,
) -> None:
    for group in ("All", team):
        bucket = metrics_by_team_month[group][result.month_key]
        _add_result_to_bucket(bucket, result)


def calculate_monthly_development_time(
    projects: list[str],
    start_date: str,
    end_date: str,
    issue_types: list[str],
) -> defaultdict[str, defaultdict[str, MonthlyDevelopmentTimeBucket]]:
    jql_query = build_development_time_jql(projects, issue_types, start_date, end_date)
    print(f"JQL Query: {jql_query}\n")
    tickets = get_tickets_from_jira(jql_query)
    verbose_print(f"Retrieved {len(tickets)} total tickets from API")
    metrics_by_team_month = defaultdict(lambda: defaultdict(MonthlyDevelopmentTimeBucket))

    for issue in tickets:
        result = calculate_total_development_window(issue)
        if not is_month_key_in_date_range(result.month_key, start_date, end_date):
            skip_message = (
                f"Skipping {result.issue_id}: result month {result.month_key} " f"is outside {start_date} to {end_date}"
            )
            verbose_print(skip_message)
            continue

        team = get_team_or_project_unknown(issue)
        _record_development_time_result(metrics_by_team_month, team, result)

    return metrics_by_team_month


def _merge_development_time_metrics(
    target: defaultdict[str, defaultdict[str, MonthlyDevelopmentTimeBucket]],
    source: defaultdict[str, defaultdict[str, MonthlyDevelopmentTimeBucket]],
) -> None:
    for team, months in source.items():
        for month, bucket in months.items():
            target_bucket = target[team][month]
            target_bucket.development_times.extend(bucket.development_times)
            target_bucket.skipped_missing_in_progress += bucket.skipped_missing_in_progress
            target_bucket.skipped_no_next_status += bucket.skipped_no_next_status


def calculate_development_time_for_date_ranges(
    projects: list[str],
    date_ranges: list[tuple[str, str]],
    issue_types: list[str],
) -> defaultdict[str, defaultdict[str, MonthlyDevelopmentTimeBucket]]:
    metrics_by_team_month = defaultdict(lambda: defaultdict(MonthlyDevelopmentTimeBucket))
    for start_date, end_date in date_ranges:
        range_metrics = calculate_monthly_development_time(projects, start_date, end_date, issue_types)
        _merge_development_time_metrics(metrics_by_team_month, range_metrics)
    return metrics_by_team_month


def _business_seconds_to_days(seconds: float) -> float:
    return seconds / (SECONDS_TO_HOURS * HOURS_TO_DAYS)


def process_development_time_metrics(
    team: str,
    months: dict[str, MonthlyDevelopmentTimeBucket],
) -> list[dict[str, str | int]]:
    metrics = []
    period_development_seconds = []
    for month, bucket in sorted(months.items()):
        development_seconds = [seconds for seconds, _ in bucket.development_times]
        median_days = _business_seconds_to_days(calculate_percentile(development_seconds, 0.50))
        p85_days = _business_seconds_to_days(calculate_percentile(development_seconds, 0.85))
        period_development_seconds.extend(development_seconds)
        metric = {
            "Team": team,
            "Month": month,
            "Median Development Time (days)": f"{median_days:.2f}",
            "P85 Development Time (days)": f"{p85_days:.2f}",
            "Ticket Count": len(bucket.development_times),
            "Skipped: missing in-progress": bucket.skipped_missing_in_progress,
            "Skipped: no next status after in-progress": bucket.skipped_no_next_status,
        }
        metrics.append(metric)
        print(
            f"Month: {month}, Median Development Time: {median_days:.2f} days, "
            f"P85 Development Time: {p85_days:.2f} days, "
            f"Ticket Count: {len(bucket.development_times)}, "
            f"Skipped missing in-progress: {bucket.skipped_missing_in_progress}, "
            f"Skipped no next status after in-progress: {bucket.skipped_no_next_status}"
        )

    period_median_days = _business_seconds_to_days(calculate_percentile(period_development_seconds, 0.50))
    period_p85_days = _business_seconds_to_days(calculate_percentile(period_development_seconds, 0.85))
    print(
        f"Selected period summary: Median Development Time: {period_median_days:.2f} days, "
        f"P85 Development Time: {period_p85_days:.2f} days, "
        f"Ticket Count: {len(period_development_seconds)}"
    )
    return metrics


def show_development_time_metrics(
    csv_output: bool,
    metrics_by_team_month: defaultdict[str, defaultdict[str, MonthlyDevelopmentTimeBucket]],
) -> list[dict[str, str | int]]:
    all_metrics = []
    all_team = metrics_by_team_month.pop("All", None)

    if all_team:
        print("Team: All")
        all_metrics.extend(process_development_time_metrics("All", all_team))

    for team, months in sorted(metrics_by_team_month.items(), key=lambda item: item[0].lower()):
        print(f"Team: {team}")
        all_metrics.extend(process_development_time_metrics(team, months))

    if csv_output:
        with open("development_times.csv", "w", newline="", encoding="utf-8") as csvfile:
            fieldnames = [
                "Team",
                "Month",
                "Median Development Time (days)",
                "P85 Development Time (days)",
                "Ticket Count",
                "Skipped: missing in-progress",
                "Skipped: no next status after in-progress",
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_metrics)
        print("Development time data has been exported to development_times.csv")
    else:
        print("To save output to a CSV file, use the -csv flag.")

    return all_metrics


def main() -> None:
    parser = get_common_parser()
    parser.add_argument(
        "--year",
        type=int,
        help="Year (YYYY) for development time metrics; defaults to the current year.",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        help="Start year (YYYY) for a multi-year development time range.",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        help="End year (YYYY) for a multi-year development time range.",
    )
    parser.add_argument(
        "--issue-types",
        required=True,
        type=parse_issue_types,
        help="Comma-separated Jira issue types to include, e.g. Story,Task,Bug.",
    )
    args = parse_common_arguments(parser)
    print_env_variables()

    try:
        date_ranges = resolve_reporting_date_ranges(args)
    except ValueError as exc:
        parser.error(str(exc))

    start_date = date_ranges[0][0]
    end_date = date_ranges[-1][1]

    try:
        projects = parse_projects_from_env()
    except ValueError as exc:
        parser.error(str(exc))

    print("Measuring development time as total completed time spent in In Progress.")
    print("P85 means 85% of measured tickets finished at or below that many business days.")
    print(f"Date range: {start_date} to {end_date}")
    if len(date_ranges) > 1:
        print(f"Query slices: {', '.join(start[:4] for start, _ in date_ranges)}")
    print(f"Projects: {projects}")
    print(f"Issue types: {args.issue_types}")
    try:
        validate_issue_types_exist(args.issue_types)
    except ValueError as exc:
        parser.error(str(exc))

    metrics_by_team_month = calculate_development_time_for_date_ranges(
        projects,
        date_ranges,
        args.issue_types,
    )
    show_development_time_metrics(args.csv, metrics_by_team_month)
    print("Completed development time measurement using total completed time spent in In Progress.")


if __name__ == "__main__":
    main()
