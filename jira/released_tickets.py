import os
from collections import defaultdict
from datetime import datetime
import pytz
import argparse
import csv
from jira import JIRA


projects = os.environ.get("JIRA_PROJECTS").split(",")
required_env_vars = ["JIRA_API_KEY", "USER_EMAIL", "JIRA_LINK", "JIRA_PROJECTS"]
for var in required_env_vars:
    if os.environ.get(var) is None:
        raise ValueError(f"Environment variable {var} is not set.")


def get_jira_instance():
    """
    Create the jira instance
    An easy way to set up your environment variables is through your .zshrc or .bashrc file
    export USER_EMAIL="your_email@example.com"
    export JIRA_API_KEY="your_jira_api_key"
    export JIRA_LINK="https://your_jira_instance.atlassian.net"
    """
    user = os.environ.get("USER_EMAIL")
    api_key = os.environ.get("JIRA_API_KEY")
    link = os.environ.get("JIRA_LINK")
    options = {
        "server": link,
    }
    return JIRA(options=options, basic_auth=(user, api_key))


def search_issues(jql):
    start_at = 0
    max_results = 100
    total_issues = []

    print(f"jql: {jql}")
    while True:
        pagination_issues = jira.search_issues(
            jql, startAt=start_at, maxResults=max_results, expand="changelog"
        )
        print(f"Received {len(pagination_issues)} tickets")
        total_issues.extend(pagination_issues)

        if len(pagination_issues) < max_results:
            break

        start_at += max_results

    print(f"Received a total of {len(total_issues)} tickets")
    return total_issues


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
CURRENT_YEAR = datetime.now().year
START_DATE = f"{CURRENT_YEAR}-01-01"
END_DATE = f"{CURRENT_YEAR}-12-31"
jira = get_jira_instance()
JQL_QUERY = f"project in ({', '.join(projects)}) AND status in (Released) and (updatedDate >= {START_DATE} and updatedDate <= {END_DATE} ) AND issueType in (Task, Bug, Story, Spike) ORDER BY updated ASC"
jql_issues = search_issues(JQL_QUERY)
jql_month_data = process_issues(jql_issues, START_DATE)

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
