import os
import argparse
from datetime import datetime
from collections import defaultdict
import csv
from jira import JIRA
from jira_utils import get_tickets_from_jira


def parse_arguments():
    # pylint: disable=global-statement
    # Define the argument parser
    parser = argparse.ArgumentParser(description="Process some tickets.")
    parser.add_argument(
        "-csv", action="store_true", help="Export the release data to a CSV file."
    )
    args = parser.parse_args()
    return args


def get_resolution_date(ticket):
    # we will not look at reversed(ticket.changelog.histories) since if the release was reverted,
    # we will not consider it as a successful release
    for history in ticket.changelog.histories:
        for item in history.items:
            if item.field == "status" and item.toString == "Released":
                return datetime.strptime(history.created, "%Y-%m-%dT%H:%M:%S.%f%z")
    return None


def get_team(ticket):
    team_field = ticket.fields.customfield_10075
    if team_field:
        return team_field.value.strip().lower().capitalize()
    project_key = ticket.fields.project.key.upper()
    default_team = os.getenv(f"TEAM_{project_key}")

    if default_team:
        return default_team.strip().lower().capitalize()

    # Environment variable for project {project_key} not found. Using project key as team
    return project_key.strip().lower().capitalize()


def get_work_type(ticket):
    work_type = ticket.fields.customfield_10079
    return work_type.value.strip() if work_type else "Product"


def update_team_data(team_data, team, month_key, work_type_value):
    if work_type_value in ["Debt Reduction", "Critical"]:
        team_data[team][month_key]["engineering_excellence"] += 1
        team_data["all"][month_key]["engineering_excellence"] += 1
    else:
        team_data[team][month_key]["product"] += 1
        team_data["all"][month_key]["product"] += 1


def categorize_ticket(ticket, team_data):
    resolution_date = get_resolution_date(ticket)
    if not resolution_date:
        print(f"Ticket {ticket.key} has no resolution date")
        return

    month_key = resolution_date.strftime("%Y-%m")
    team = get_team(ticket)
    work_type_value = get_work_type(ticket)
    update_team_data(team_data, team, month_key, work_type_value)


def show_team_metrics(team_data, csv_output):
    all_metrics = []
    for team, months in sorted(team_data.items()):
        print(f"Team {team.capitalize()}")

        cumulative_ee = 0
        cumulative_total = 0

        for month, data in sorted(months.items()):
            total_tickets = data["engineering_excellence"] + data["product"]
            if total_tickets > 0:
                product_focus_percent = (data["product"] / total_tickets) * 100
                engineering_excellence_percent = (
                    data["engineering_excellence"] / total_tickets
                ) * 100
            else:
                product_focus_percent = 0
                engineering_excellence_percent = 0

            # Update cumulative counts
            cumulative_ee += data["engineering_excellence"]
            cumulative_total += total_tickets
            # Calculate yearly average EE percentage up to this month
            if cumulative_total > 0:
                annual_ee_average = (cumulative_ee / cumulative_total) * 100
            else:
                annual_ee_average = 0

            print(
                f"  {month} Total tickets: {total_tickets}, product focus: {data['product']} [{product_focus_percent:.2f}%], engineering excellence: {data['engineering_excellence']} [{engineering_excellence_percent:.2f}%], annual ee average: {annual_ee_average:.2f}%"
            )
            all_metrics.append(
                {
                    "Team": team.capitalize(),
                    "Month": month,
                    "Product Focus Percentage": f"{product_focus_percent:.2f}%",
                    "Engineering Excellence Percentage": f"{engineering_excellence_percent:.2f}%",
                    "Product Focus Tickets": data["product"],
                    "Engineering Excellence Tickets": data["engineering_excellence"],
                }
            )
    if csv_output:
        with open("engineering_excellence.csv", "w", newline="") as csvfile:
            fieldnames = [
                "Team",
                "Month",
                "Product Focus Percentage",
                "Engineering Excellence Percentage",
                "Product Focus Tickets",
                "Engineering Excellence Tickets",
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_metrics)
        print(
            "Engineering excellence data has been exported to engineering_excellence.csv"
        )
    else:
        print("To save output to a CSV file, use the -csv flag.")


def extract_engineering_excellence(jql_query):
    released_tickets = get_tickets_from_jira(jql_query)
    team_data = defaultdict(
        lambda: defaultdict(lambda: {"engineering_excellence": 0, "product": 0})
    )
    print(f"Total number of tickets retrieved: {len(released_tickets)}")

    for ticket in released_tickets:
        categorize_ticket(ticket, team_data)
    return team_data


def main():
    current_year = datetime.now().year
    start_date = f"{current_year}-01-01"
    end_date = f"{current_year}-12-31"
    # Modified JQL query to filter tickets that changed to "Released" status within the given timeframe
    projects = os.environ.get("JIRA_PROJECTS").split(",")
    jql_query = f"project in ({', '.join(projects)})  AND status changed to Released during ({start_date}, {end_date}) AND issueType in (Task, Bug, Story, Spike) ORDER BY updated ASC"
    team_data = extract_engineering_excellence(jql_query)
    args = parse_arguments()
    show_team_metrics(team_data, args.csv)


if __name__ == "__main__":
    main()
