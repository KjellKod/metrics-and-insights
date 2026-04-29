"""Monthly Jira bug health reporting for company and team dashboards."""

import argparse
import csv
import os
import re
from datetime import date, datetime, time
from pathlib import Path

from dotenv import load_dotenv

# pylint: disable=import-error
from jira_utils import (
    get_common_parser,
    get_completion_statuses,
    get_team,
    get_tickets_from_jira,
    parse_common_arguments,
    print_env_variables,
    verbose_print,
)

load_dotenv()

DEFAULT_SLA_DAYS = {
    "P0": 0,
    "P1": 1,
    "P2": 10,
    "P3": 20,
}

SUMMARY_FIELDNAMES = [
    "period",
    "scope_type",
    "scope",
    "priority",
    "created_count",
    "closed_count",
    "net_change",
    "open_backlog_count",
    "sla_breached_count",
    "sla_breach_rate",
    "missing_priority_count",
    "missing_due_date_count",
    "median_days_to_close",
    "p85_days_to_close",
]

DETAIL_FIELDNAMES = [
    "period",
    "ticket_key",
    "team",
    "project",
    "created_date",
    "completion_date",
    "status",
    "effective_priority",
    "priority_source",
    "due_date",
    "sla_target",
    "sla_breached",
    "days_open_or_to_close",
    "included_in_created",
    "included_in_closed",
    "included_in_backlog",
    "summary",
]


def parse_date(value):
    """Parse a CLI date value in YYYY-MM-DD format."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Expected date in YYYY-MM-DD format") from exc


def parse_jira_datetime(value):
    """Parse Jira datetime/date strings into timezone-aware or naive datetimes."""
    if not value:
        return None

    if isinstance(value, datetime):
        return value

    if isinstance(value, date):
        return datetime.combine(value, time.min)

    formats = [
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue

    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        verbose_print(f"Could not parse Jira datetime: {value}")
        return None


def to_date(value):
    parsed = parse_jira_datetime(value)
    return parsed.date() if parsed else None


def month_end(year, month):
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1).replace(day=1) - date.resolution


def iter_month_buckets(start_date, end_date):
    """Yield monthly buckets clipped to the requested date range."""
    current = date(start_date.year, start_date.month, 1)
    while current <= end_date:
        end = month_end(current.year, current.month)
        yield {
            "label": current.strftime("%Y-%m"),
            "start": max(start_date, current),
            "end": min(end_date, end),
        }
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)


def quote_jql_value(value):
    return f'"{value.replace(chr(34), chr(92) + chr(34))}"'


def format_status_list(statuses):
    return ", ".join(quote_jql_value(status.title()) for status in statuses)


def format_project_clause(projects):
    if projects is None:
        return ""
    cleaned_projects = [project.strip().strip("'\"") for project in projects if project.strip()]
    quoted_projects = [f"'{project}'" for project in cleaned_projects]
    return f"project IN ({', '.join(quoted_projects)}) AND "


def build_jql_queries(start_date, end_date, projects=None):
    """Build bounded Jira queries for one reporting period."""
    project_clause = format_project_clause(projects)
    status_list = format_status_list(get_completion_statuses())
    start = start_date.isoformat()
    end = end_date.isoformat()

    return {
        "created": f"{project_clause}issuetype = Bug AND created >= '{start}' AND created <= '{end}' ORDER BY updated ASC",
        "closed_workflow": (
            f"{project_clause}issuetype = Bug AND status CHANGED TO ({status_list}) "
            f"DURING ('{start}', '{end}') ORDER BY updated ASC"
        ),
        "closed_resolved": (
            f"{project_clause}issuetype = Bug AND resolved >= '{start}' AND resolved <= '{end}' ORDER BY updated ASC"
        ),
        "backlog": (
            f"{project_clause}issuetype = Bug AND created <= '{end}' "
            f"AND status WAS NOT IN ({status_list}) ON '{end}' "
            f"AND (resolved IS EMPTY OR resolved > '{end}') ORDER BY updated ASC"
        ),
    }


def get_field_value(field):
    if not field:
        return None
    if hasattr(field, "value"):
        return field.value
    if isinstance(field, dict):
        return field.get("value")
    return field


def get_bug_priority(ticket):
    custom_field_id = os.getenv("CUSTOM_FIELD_BUG_PRIORITY")
    if custom_field_id:
        custom_field = getattr(ticket.fields, f"customfield_{custom_field_id}", None)
        custom_value = get_field_value(custom_field)
        if custom_value:
            return str(custom_value), "bug_priority"

    priority = getattr(ticket.fields, "priority", None)
    priority_name = getattr(priority, "name", None) if priority else None
    if priority_name:
        return str(priority_name), "jira_priority"

    return "Unset", "unset"


def normalize_priority(priority):
    """Normalize common P0-P4 priority labels for SLA lookup."""
    if not priority or priority == "Unset":
        return "Unset"
    match = re.search(r"\bP([0-4])\b", priority.upper())
    if match:
        return f"P{match.group(1)}"
    return priority.strip()


def parse_sla_days(raw_value=None):
    """Parse BUG_HEALTH_SLA_DAYS env format: P0:0,P1:1,P2:10,P3:20."""
    if raw_value is None:
        raw_value = os.getenv("BUG_HEALTH_SLA_DAYS")
    if not raw_value:
        return dict(DEFAULT_SLA_DAYS)

    parsed = {}
    for part in raw_value.split(","):
        if not part.strip():
            continue
        key, _, value = part.partition(":")
        key = key.strip().upper()
        value = value.strip()
        if not key or value == "":
            continue
        parsed[key] = int(value)
    return parsed


def extract_completion_date(ticket):
    """Return earliest available completion date from completion statuses or resolutiondate."""
    candidates = []
    completion_statuses = set(get_completion_statuses())

    if hasattr(ticket, "changelog") and hasattr(ticket.changelog, "histories"):
        for history in ticket.changelog.histories:
            history_date = parse_jira_datetime(getattr(history, "created", None))
            if not history_date:
                continue
            for item in getattr(history, "items", []):
                if item.field == "status" and item.toString and item.toString.lower() in completion_statuses:
                    candidates.append(history_date)

    resolution_date = parse_jira_datetime(getattr(ticket.fields, "resolutiondate", None))
    if resolution_date:
        candidates.append(resolution_date)

    return min(candidates) if candidates else None


def days_between(start_date, end_date):
    if not start_date or not end_date:
        return None
    return max((end_date - start_date).days, 0)


def percentile(values, percentile_value):
    if not values:
        return ""
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * percentile_value))
    return round(ordered[index], 2)


def median(values):
    if not values:
        return ""
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[middle], 2)
    return round((ordered[middle - 1] + ordered[middle]) / 2, 2)


def ticket_to_detail(ticket, period, included, sla_days):
    priority, priority_source = get_bug_priority(ticket)
    normalized_priority = normalize_priority(priority)
    created_date = to_date(getattr(ticket.fields, "created", None))
    completion_datetime = extract_completion_date(ticket)
    completion_date = completion_datetime.date() if completion_datetime else None
    due_date = to_date(getattr(ticket.fields, "duedate", None))
    closed_in_period = (
        ticket.key in included["closed"]
        and completion_date is not None
        and period["start"] <= completion_date <= period["end"]
    )
    end_for_age = completion_date if closed_in_period else period["end"]
    age_days = days_between(created_date, end_for_age)
    sla_target = sla_days.get(normalized_priority)
    sla_breached = bool(sla_target is not None and age_days is not None and age_days > sla_target)

    return {
        "period": period["label"],
        "ticket_key": ticket.key,
        "team": get_team(ticket),
        "project": ticket.fields.project.key,
        "created_date": created_date.isoformat() if created_date else "",
        "completion_date": completion_date.isoformat() if completion_date else "",
        "status": getattr(ticket.fields.status, "name", ""),
        "effective_priority": normalized_priority,
        "priority_source": priority_source,
        "due_date": due_date.isoformat() if due_date else "",
        "sla_target": sla_target if sla_target is not None else "",
        "sla_breached": sla_breached,
        "days_open_or_to_close": age_days if age_days is not None else "",
        "included_in_created": ticket.key in included["created"],
        "included_in_closed": ticket.key in included["closed"],
        "included_in_backlog": ticket.key in included["backlog"],
        "summary": getattr(ticket.fields, "summary", "") or "",
    }


def empty_summary_row(period, scope_type, scope, priority):
    return {
        "period": period,
        "scope_type": scope_type,
        "scope": scope,
        "priority": priority,
        "created_count": 0,
        "closed_count": 0,
        "net_change": 0,
        "open_backlog_count": 0,
        "sla_breached_count": 0,
        "sla_breach_rate": 0,
        "missing_priority_count": 0,
        "missing_due_date_count": 0,
        "median_days_to_close": "",
        "p85_days_to_close": "",
        "_closed_durations": [],
        "_sla_evaluable_count": 0,
    }


def add_detail_to_summary(summary, detail):
    if detail["included_in_created"]:
        summary["created_count"] += 1
    if detail["included_in_closed"]:
        summary["closed_count"] += 1
    if detail["included_in_backlog"]:
        summary["open_backlog_count"] += 1
    if detail["sla_breached"]:
        summary["sla_breached_count"] += 1
    if detail["sla_target"] != "":
        summary["_sla_evaluable_count"] += 1
    if detail["priority_source"] == "unset":
        summary["missing_priority_count"] += 1
    if not detail["due_date"]:
        summary["missing_due_date_count"] += 1
    if detail["included_in_closed"] and detail["days_open_or_to_close"] != "":
        summary["_closed_durations"].append(detail["days_open_or_to_close"])


def finalize_summary(row):
    row["net_change"] = row["created_count"] - row["closed_count"]
    denominator = row["_sla_evaluable_count"]
    row["sla_breach_rate"] = round(row["sla_breached_count"] / denominator, 4) if denominator else 0
    row["median_days_to_close"] = median(row["_closed_durations"])
    row["p85_days_to_close"] = percentile(row["_closed_durations"], 0.85)
    row.pop("_closed_durations", None)
    row.pop("_sla_evaluable_count", None)
    return row


def aggregate_summary(details):
    summaries = {}

    for detail in details:
        scopes = [("company", "all"), ("team", detail["team"])]
        priorities = ["all", detail["effective_priority"]]
        for scope_type, scope in scopes:
            for priority in priorities:
                key = (detail["period"], scope_type, scope, priority)
                if key not in summaries:
                    summaries[key] = empty_summary_row(detail["period"], scope_type, scope, priority)
                add_detail_to_summary(summaries[key], detail)

    return [finalize_summary(row) for row in summaries.values()]


def fetch_period_details(period, projects, sla_days):
    queries = build_jql_queries(period["start"], period["end"], projects)
    tickets_by_key = {}
    included = {
        "created": set(),
        "closed": set(),
        "backlog": set(),
    }

    for metric, query in queries.items():
        tickets = get_tickets_from_jira(query)
        verbose_print(f"{period['label']} {metric}: {len(tickets)} tickets")
        target = "closed" if metric in {"closed_workflow", "closed_resolved"} else metric
        for ticket in tickets:
            tickets_by_key[ticket.key] = ticket
            included[target].add(ticket.key)

    return [ticket_to_detail(ticket, period, included, sla_days) for ticket in tickets_by_key.values()]


def generate_bug_health_report(start_date, end_date, projects=None):
    sla_days = parse_sla_days()
    details = []
    for period in iter_month_buckets(start_date, end_date):
        details.extend(fetch_period_details(period, projects, sla_days))
    summaries = aggregate_summary(details)
    summaries.sort(key=lambda row: (row["period"], row["scope_type"], row["scope"], row["priority"]))
    details.sort(key=lambda row: (row["period"], row["team"], row["ticket_key"]))
    return summaries, details


def write_csv(rows, fieldnames, output_file):
    with open(output_file, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return output_file


def format_signed(value):
    return f"+{value}" if value > 0 else str(value)


def format_percent(value):
    return f"{value * 100:.1f}%"


def company_all_rows(summaries):
    return [
        row
        for row in summaries
        if row["scope_type"] == "company" and row["scope"] == "all" and row["priority"] == "all"
    ]


def latest_company_row(summaries):
    rows = company_all_rows(summaries)
    return max(rows, key=lambda row: row["period"]) if rows else None


def latest_team_rows(summaries, period):
    return [
        row
        for row in summaries
        if row["period"] == period and row["scope_type"] == "team" and row["priority"] == "all"
    ]


def render_console_summary(summaries, details):
    """Render a concise human summary for terminal output."""
    if not summaries:
        return "Bug health summary\nNo matching bugs found for this date range."

    company_rows = sorted(company_all_rows(summaries), key=lambda row: row["period"])
    latest = latest_company_row(summaries)
    if not latest:
        return "Bug health summary\nNo company-level summary rows were generated."

    created_total = sum(row["created_count"] for row in company_rows)
    closed_total = sum(row["closed_count"] for row in company_rows)
    period_start = company_rows[0]["period"]
    period_end = company_rows[-1]["period"]
    total_unique_tickets = len({detail["ticket_key"] for detail in details})

    lines = [
        "",
        "Bug health summary",
        f"- Range: {period_start} to {period_end}; unique bugs seen: {total_unique_tickets}",
        f"- Flow: created {created_total}, closed {closed_total}, net {format_signed(created_total - closed_total)}",
        (
            f"- Latest period {latest['period']}: created {latest['created_count']}, "
            f"closed {latest['closed_count']}, net {format_signed(latest['net_change'])}, "
            f"backlog {latest['open_backlog_count']}"
        ),
        (
            f"- SLA/data quality: breached {latest['sla_breached_count']} "
            f"({format_percent(latest['sla_breach_rate'])}), "
            f"missing priority {latest['missing_priority_count']}, "
            f"missing due date {latest['missing_due_date_count']}"
        ),
    ]

    if latest["median_days_to_close"] != "":
        lines.append(
            f"- Close time: median {latest['median_days_to_close']} days, p85 {latest['p85_days_to_close']} days"
        )

    team_rows = latest_team_rows(summaries, latest["period"])
    attention_rows = sorted(
        team_rows,
        key=lambda row: (row["sla_breached_count"], row["open_backlog_count"], row["net_change"]),
        reverse=True,
    )[:3]
    if attention_rows:
        lines.append("- Teams to inspect:")
        for row in attention_rows:
            lines.append(
                f"  {row['scope']}: backlog {row['open_backlog_count']}, "
                f"net {format_signed(row['net_change'])}, SLA breached {row['sla_breached_count']}"
            )

    return "\n".join(lines)


def parse_arguments():
    parser = get_common_parser()
    parser.description = "Generate monthly Jira bug health CSVs"
    parser.add_argument("--start-date", type=parse_date, required=True, help="Start date for analysis (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=parse_date, required=True, help="End date for analysis (YYYY-MM-DD)")
    parser.add_argument("--all-projects", action="store_true", help="Analyze all Jira projects")
    parser.add_argument("--output-dir", default=".", help="Directory where CSV files should be written")
    args = parse_common_arguments(parser)
    if args.start_date > args.end_date:
        raise ValueError("Start date cannot be greater than end date")
    return args


def main():
    args = parse_arguments()
    print_env_variables()

    projects = None
    if not args.all_projects:
        raw_projects = os.getenv("JIRA_PROJECTS")
        if not raw_projects:
            raise ValueError("JIRA_PROJECTS must be set unless --all-projects is used")
        projects = [project.strip().strip("'\"") for project in raw_projects.split(",") if project.strip()]

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    summaries, details = generate_bug_health_report(args.start_date, args.end_date, projects)
    start = args.start_date.isoformat()
    end = args.end_date.isoformat()
    summary_file = output_dir / f"bug_health_summary_{start}_to_{end}.csv"
    detail_file = output_dir / f"bug_health_details_{start}_to_{end}.csv"

    write_csv(summaries, SUMMARY_FIELDNAMES, summary_file)
    write_csv(details, DETAIL_FIELDNAMES, detail_file)

    print(f"Bug health summary exported to {summary_file}")
    print(f"Bug health details exported to {detail_file}")
    print(render_console_summary(summaries, details))


if __name__ == "__main__":
    main()
