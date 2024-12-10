import os
from collections import defaultdict
from datetime import datetime
import csv
import pytz

# pylint: disable=import-error
from jira_utils import (
    get_tickets_from_jira,
    parse_arguments,
    verbose_print,
    JiraStatus,
    extract_status_timestamps,
    interpret_status_timestamps,
    get_ticket_points,
)

projects = os.environ.get("JIRA_PROJECTS").split(",")


def get_resolution_date(ticket):
    status_timestamps = extract_status_timestamps(ticket)
    extracted_statuses = interpret_status_timestamps(status_timestamps)
    return extracted_statuses[JiraStatus.RELEASED.value]


def process_issues(issues, start_date_str, end_date_str):
    # Convert start_date_str to a datetime object and make it offset-aware with PST timezone
    pst = pytz.timezone("America/Los_Angeles")
    start_date = pst.localize(datetime.strptime(start_date_str, "%Y-%m-%d"))
    end_date = pst.localize(datetime.strptime(end_date_str, "%Y-%m-%d"))
    month_data = defaultdict(lambda: {"released_tickets_count": 0, "released_tickets": [], "total_points": 0})

    for issue in issues:
        released_date = get_resolution_date(issue)
        # Check if the updated_date is greater than or equal to start_date
        if released_date < start_date or released_date > end_date:
            verbose_print(f"Ignored: {issue.key}. Released {released_date}, start_date/end:{start_date}/{end_date}")
            continue

        month_key = released_date.strftime("%Y-%m")
        issue_key = issue.key
        points = get_ticket_points(issue)
        month_data[month_key]["released_tickets_count"] += 1
        month_data[month_key]["released_tickets"].append(f"{issue_key}")
        # Using points IS sketcy, since it's a complete changeable, team-owned variable.
        # it CAN make sense to show patterns emerging, and strengthening the picture from other metrics
        # such as ticket count, but it's not a reliable metric on its own.
        month_data[month_key]["total_points"] += points

    return month_data


# Process the issues
def analyze_release_tickets(jql_month_data):
    # Output the data in comma-separated format
    print("\nJQL Query Results:")
    for month, data in jql_month_data.items():
        print(f"\nMonth: {month}")
        print(f"Released Tickets Count: {data['released_tickets_count']}")
        print(f"Total Points: {data['total_points']}")  # points IS sketcy, but we can use it with other metrics
        verbose_print(f"Released Tickets: {', '.join(data['released_tickets'])}")


def show_result(jql_month_data, args):
    # Export to CSV if the -csv flag is provided
    if args.csv:
        with open("released_tickets.csv", "w", newline="", encoding="utf-8") as csvfile:
            fieldnames = ["Month", "Released Ticket Count", "Total Points"]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader()
            for month, data in jql_month_data.items():
                writer.writerow(
                    {
                        "Month": month,
                        "Released Ticket Count": data["released_tickets_count"],
                        "Total Points": data["total_points"],
                    }
                )

        print("Released ticket data has been exported to released_tickets.csv")
    else:
        print("No CSV flag provided (-csv), no data exported.")


def main():
    args = parse_arguments()
    args.csv = True
    current_year = datetime.now().year
    start_date = f"{current_year}-01-01"
    end_date = f"{current_year}-12-31"
    jql_query = f"project in ({', '.join(projects)}) AND status in (Released) and status changed to Released during ({start_date}, {end_date}) AND issueType in (Task, Bug, Story, Spike) ORDER BY updated ASC"
    jql_issues = get_tickets_from_jira(jql_query)
    jql_month_data = process_issues(jql_issues, start_date, end_date)
    analyze_release_tickets(jql_month_data)
    show_result(jql_month_data, args)


if __name__ == "__main__":
    main()
