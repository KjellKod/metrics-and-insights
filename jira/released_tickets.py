import os
from collections import defaultdict
from datetime import datetime
import argparse
import csv
import pytz
from jira_utils import get_tickets_from_jira, parse_arguments

projects = os.environ.get("JIRA_PROJECTS").split(",")


def get_resolution_date(ticket):
    # we will not look at reversed(ticket.changelog.histories) since if the release was reverted,
    # we will not consider it as a successful release
    for history in ticket.changelog.histories:
        for item in history.items:
            if item.field == "status" and item.toString == "Released":
                print(f"Found resolution date: {history.created}")
                return datetime.strptime(history.created, "%Y-%m-%dT%H:%M:%S.%f%z")
    return None


def process_issues(issues, start_date_str):
    # Convert start_date_str to a datetime object and make it offset-aware with PST timezone
    pst = pytz.timezone("America/Los_Angeles")
    start_date = pst.localize(datetime.strptime(start_date_str, "%Y-%m-%d"))
    month_data = defaultdict(
        lambda: {"released_tickets_count": 0, "released_tickets": []}
    )

    for issue in issues:
        released_date = get_resolution_date(issue)
        # Check if the updated_date is greater than or equal to start_date
        if released_date < start_date:
            continue

        month_key = released_date.strftime("%Y-%m")
        issue_key = issue.key

        month_data[month_key]["released_tickets_count"] += 1
        month_data[month_key]["released_tickets"].append(f"{issue_key}")

    return month_data


# Process the issues
def analyze_release_tickets(jql_month_data, start_date_str, end_date_str):
    # Output the data in comma-separated format
    print("\nJQL Query Results:")
    for month, data in jql_month_data.items():
        print(f"\nMonth: {month}")
        print(f"Released Tickets Count: {data['released_tickets_count']}")
        print(f"Released Tickets: {', '.join(data['released_tickets'])}")


# Parse command-line arguments
parser = argparse.ArgumentParser(
    description="Retrieve and optionally export GitHub releases to CSV."
)
parser.add_argument(
    "-csv", action="store_true", help="Export the release data to a CSV file."
)
args = parser.parse_args()


def show_result(jql_month_data, args):
    # Export to CSV if the -csv flag is provided
    if args.csv:
        with open("released_tickets.csv", "w", newline="") as csvfile:
            fieldnames = ["Month", "Released Ticket Count"]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader()
            for month, data in jql_month_data.items():
                writer.writerow(
                    {
                        "Month": month,
                        "Released Ticket Count": data["released_tickets_count"],
                    }
                )

        print("Released ticket data has been exported to released_tickets.csv")
    else:
        print("No CSV flag provided (-csv), no data exported.")


def main():
    args = parse_arguments()
    current_year = datetime.now().year
    start_date = f"{current_year}-01-01"
    end_date = f"{current_year}-12-31"
    jql_query = f"project in ({', '.join(projects)}) AND status in (Released) and status changed to Released during ({start_date}, {end_date}) AND issueType in (Task, Bug, Story, Spike) ORDER BY updated ASC"
    jql_issues = get_tickets_from_jira(jql_query)
    jql_month_data = process_issues(jql_issues, start_date)
    analyze_release_tickets(jql_month_data, start_date, end_date)
    show_result(jql_month_data, args)


if __name__ == "__main__":
    main()
