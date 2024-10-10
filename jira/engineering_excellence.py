import os
from datetime import datetime
from collections import defaultdict
from jira import JIRA

# Jira API endpoint
projects = os.environ.get("JIRA_PROJECTS").split(",")


def get_jira_instance():
    """
    Create the jira instance
    An easy way to set up your environment variables is through your .zshrc or .bashrc file
    export USER_EMAIL="your_email@example.com"
    export JIRA_API_KEY="your_jira_api_key"
    export JIRA_LINK="https://your_jira_instance.atlassian.net"
    export JIRA_PROJECTS="ENG, ONF, INT"
    """
    user = os.environ.get("USER_EMAIL")
    api_key = os.environ.get("JIRA_API_KEY")
    link = os.environ.get("JIRA_LINK")
    options = {
        "server": link,
    }
    required_env_vars = ["JIRA_API_KEY", "USER_EMAIL", "JIRA_LINK", "JIRA_PROJECTS"]
    for var in required_env_vars:
        if os.environ.get(var) is None:
            raise ValueError(f"Environment variable {var} is not set.")
    jira = JIRA(options=options, basic_auth=(user, api_key))
    return jira


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


def print_team_metrics(team_data):
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


def search_issues(jql):
    start_at = 0
    max_results = 100
    total_issues = []
    jira = get_jira_instance()
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


def extract_engineering_excellence(jql_query):
    released_tickets = search_issues(jql_query)
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
    jql_query = f"project in ({', '.join(projects)})  AND status changed to Released during ({start_date}, {end_date}) AND issueType in (Task, Bug, Story, Spike) ORDER BY updated ASC"
    print(jql_query)

    team_data = extract_engineering_excellence(jql_query)
    print_team_metrics(team_data)


if __name__ == "__main__":
    main()
