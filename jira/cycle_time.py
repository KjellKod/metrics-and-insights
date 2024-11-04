import os
from collections import defaultdict
from datetime import datetime, timedelta
import statistics
import argparse
import csv
import pytz
from jira.resources import Issue
from jira_utils import get_tickets_from_jira, get_team

# Global variable for verbosity
VERBOSE = False


def parse_arguments():
    # pylint: disable=global-statement
    # Define the argument parser
    global VERBOSE
    parser = argparse.ArgumentParser(description="Process some tickets.")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose output"
    )
    parser.add_argument(
        "-csv", action="store_true", help="Export the release data to a CSV file."
    )
    args = parser.parse_args()
    VERBOSE = args.verbose
    return args


projects = os.environ.get("JIRA_PROJECTS").split(",")

HOURS_TO_DAYS = 8
SECONDS_TO_HOURS = 3600


def verbose_print(message):
    if VERBOSE:
        print(message)


def validate_issue(issue):
    if not isinstance(issue, Issue):
        print(f"Unexpected type: {type(issue)}  -- ignoring")
        return False
    return True


def business_time_spent_in_seconds(start, end):
    """extract only the time spent during business hours from a jira time range -- only count 8h"""
    weekdays = [0, 1, 2, 3, 4]  # Monday to Friday
    total_business_seconds = 0
    seconds_in_workday = 8 * 60 * 60  # 8 hours * 60 minutes * 60 seconds

    current = start
    while current <= end:
        if current.weekday() in weekdays:
            day_end = current.replace(hour=23, minute=59)
            remaining_time_today = day_end - current

            if current.date() != end.date():
                total_business_seconds += min(
                    remaining_time_today.total_seconds(), seconds_in_workday
                )
                current += timedelta(days=1)
                current = current.replace(hour=0, minute=0)
            else:
                remaining_time_on_last_day = end - current
                total_business_seconds += min(
                    remaining_time_on_last_day.total_seconds(), seconds_in_workday
                )
                break
        else:
            current += timedelta(days=1)
            current = current.replace(hour=0, minute=0)

    return total_business_seconds


def localize_start_date(start_date_str):
    pst = pytz.timezone("America/Los_Angeles")
    return pst.localize(datetime.strptime(start_date_str, "%Y-%m-%d"))


def log_process_changelog(changelog):
    # Create the complete log string first
    log_string = ""
    count = 0
    for history in reversed(changelog.histories):
        for item in history.items:
            if item.field == "status":
                status = item.toString
                count = count + 1
                log_string += f"{count} -- {history.author}, {history.created}, {item.fromString} ---> {status}\n"
    return log_string


def process_changelog(changelog, start_date):
    code_review_statuses = {
        "code review",
        "in code review",
        "to review",
        "to code review",
        "in review",
        "in design review",
    }
    code_review_timestamp = None
    released_timestamp = None

    # we look at in chronological order and the FIRST time we go into code-review
    for history in reversed(changelog.histories):
        for item in history.items:
            if item.field == "status":
                status = item.toString
                if status.lower() in code_review_statuses:
                    code_review_timestamp = datetime.strptime(
                        history.created, "%Y-%m-%dT%H:%M:%S.%f%z"
                    )
                    break
    # look at the histories in reverse-chronological order to find the LAST time it was released.
    for history in changelog.histories:
        for item in history.items:
            if item.field == "status":
                status = item.toString
                if status.lower() == "released":
                    released_timestamp = datetime.strptime(
                        history.created, "%Y-%m-%dT%H:%M:%S.%f%z"
                    )
                    if start_date > released_timestamp:
                        return None, None
                    break
    return code_review_timestamp, released_timestamp


def calculate_business_time(code_review_timestamp, released_timestamp):
    business_seconds = business_time_spent_in_seconds(
        code_review_timestamp, released_timestamp
    )
    business_days = business_seconds / (SECONDS_TO_HOURS * HOURS_TO_DAYS)
    return business_seconds, business_days


def calculate_cycle_time_seconds(start_date_str, issue):
    if not validate_issue(issue):
        return None, None

    start_date = localize_start_date(start_date_str)
    code_review_timestamp, released_timestamp = process_changelog(
        issue.changelog, start_date
    )
    log_string = log_process_changelog(issue.changelog)

    if released_timestamp and code_review_timestamp:
        business_seconds, business_days = calculate_business_time(
            code_review_timestamp, released_timestamp
        )
        log_string = ""
        log_string += f"{issue.key} cycle time in business hours: {business_seconds / SECONDS_TO_HOURS:.2f} --> days: {business_seconds / (SECONDS_TO_HOURS * 8):.2f}\n"
        log_string += f"Review started at: {code_review_timestamp}, released at: {released_timestamp}, Cycle time: {business_days} days\n"
        log_string += f"Cycle time in hours: {business_seconds / 3600:.2f} --> days: {business_seconds / (3600 * 8):.2f}\n"

        month_key = released_timestamp.strftime("%Y-%m")
        verbose_print(f"Processing {issue.key}\n{log_string}")
        return business_seconds, month_key
    return None, None


def calculate_monthly_cycle_time(start_date, end_date):
    jql_query = f"project in ({', '.join(projects)}) AND status in (Released) AND status changed to Released during ({start_date}, {end_date}) AND issueType in (Task, Bug, Story, Spike) ORDER BY updated ASC"
    tickets = get_tickets_from_jira(jql_query)
    cycle_times_per_month = defaultdict(lambda: defaultdict(list))

    for _, issue in enumerate(tickets):
        cycle_time, month_key = calculate_cycle_time_seconds(start_date, issue)
        issue_id = issue.key
        if cycle_time:
            team = get_team(issue)
            cycle_times_per_month[team][month_key].append((cycle_time, issue_id))
            cycle_times_per_month["all"][month_key].append((cycle_time, issue_id))

    return cycle_times_per_month


def calculate_average_cycle_time(cycle_times):
    if cycle_times:
        total_cycle_time = sum(cycle_time for cycle_time, _ in cycle_times)
        return total_cycle_time / len(cycle_times)
    return 0


def calculate_median_cycle_time(cycle_times):
    if cycle_times:
        cycle_times_values = [cycle_time for cycle_time, _ in cycle_times]
        return statistics.median(cycle_times_values)
    return 0


def process_cycle_time_metrics(team, months):
    metrics = []
    for month, cycle_times in sorted(months.items()):
        average_cycle_time_s = calculate_average_cycle_time(cycle_times)
        median_cycle_time_s = calculate_median_cycle_time(cycle_times)
        median_cycle_time_days = median_cycle_time_s / (
            SECONDS_TO_HOURS * HOURS_TO_DAYS
        )
        average_cycle_time_days = average_cycle_time_s / (
            SECONDS_TO_HOURS * HOURS_TO_DAYS
        )
        metrics.append(
            {
                "Team": team.capitalize(),
                "Month": month,
                "Median Cycle Time (days)": f"{median_cycle_time_days:.2f}",
                "Average Cycle Time (days)": f"{average_cycle_time_days:.2f}",
            }
        )
        print(
            f"Month: {month}, Average Cycle Time: {average_cycle_time_days:.2f} days, Median Cycle Time: {median_cycle_time_days:.2f} days"
        )
    return metrics


def show_cycle_time_metrics(csv_output, cycle_times_per_month):
    # Separate the "all" team from other teams
    all_team = cycle_times_per_month.pop("all", None)

    all_metrics = []

    # Process metrics for all other teams
    for team, months in sorted(cycle_times_per_month.items()):
        print(f"Team: {team.capitalize()}")
        metrics = process_cycle_time_metrics(team, months)
        all_metrics.extend(metrics)

    # Process metrics for the "all" team
    if all_team:
        print("Team: All")
        metrics = process_cycle_time_metrics("All", all_team)
        all_metrics.extend(metrics)

    if csv_output:
        with open("cycle_times.csv", "w", newline="", encoding="utf-8") as csvfile:
            fieldnames = [
                "Team",
                "Month",
                "Median Cycle Time (days)",
                "Average Cycle Time (days)",
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_metrics)
        print("Cycle time data has been exported to cycle_times.csv")
    else:
        print("To save output to a CSV file, use the -csv flag.")


def main():
    args = parse_arguments()
    current_year = datetime.now().year
    start_date = f"{current_year}-01-01"
    end_date = f"{current_year}-12-31"
    cycle_times_per_month = calculate_monthly_cycle_time(start_date, end_date)
    show_cycle_time_metrics(args.csv, cycle_times_per_month)


if __name__ == "__main__":
    main()
