import os
from jira import JIRA
from collections import defaultdict
from datetime import datetime

# Jira API endpoint
username = os.environ.get('USER_EMAIL')
api_key = os.environ.get('JIRA_API_KEY')
jira_url = os.environ.get('JIRA_LINK')

required_env_vars = ["JIRA_API_KEY", "USER_EMAIL", "JIRA_LINK"]



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
    jira = JIRA(options=options, basic_auth=(user, api_key))
    return jira

def calculate_monthly_average_cycle_time(start_date, end_date):
    # Get the Jira instance
    jira = get_jira_instance()
    jql_query = f"project in (ONF, ENG, MOB) AND status in (Released) and (updatedDate >= 2024-01-01 and updatedDate <= 2024-12-31) AND issueType in (Task, Bug, Story, Spike) ORDER BY updated ASC"
    tickets = jira.search_issues(jql_query, maxResults=None, fields=["key", "changelog"])
    cycle_times_per_month = defaultdict(list)

    # print number of tickets received
    print(f"Received {len(tickets)} tickets")

    # Iterate over the tickets and calculate cycle time
    for ticket in tickets:
        issue = jira.issue(ticket.key, expand="changelog")
        changelog = issue.changelog

        in_progress_time = None
        released_time = None
        current_month = ""

        for history in changelog.histories:
            for item in history.items:
                if item.field == "status":
                    if item.toString == "In Progress" and not in_progress_time: 
                        in_progress_time = datetime.strptime(history.created, "%Y-%m-%dT%H:%M:%S.%f%z")
                    elif item.toString in ["Released", "Done"] and not released_time: 
                        released_time = datetime.strptime(history.created, "%Y-%m-%dT%H:%M:%S.%f%z")
                        break
            if released_time:
                break

        if in_progress_time and released_time:
            cycle_time = released_time - in_progress_time
            month_key = released_time.strftime("%Y-%m")
            cycle_times_per_month[month_key].append(cycle_time.total_seconds())

            if month_key != current_month:
                current_month = month_key
                print(f"Processing tickets for month: {current_month}")
                
    # Calculate and print the average cycle time per month
    for month, cycle_times in cycle_times_per_month.items():
        if cycle_times:
            average_cycle_time = sum(cycle_times) / len(cycle_times)
            average_cycle_time_days = average_cycle_time / (60 * 60 * 24)  # Convert seconds to days
            print(f"Month: {month}")
            print(f"Average Cycle Time: {average_cycle_time_days:.2f} days")
            print("---")
        else:
            print(f"Month: {month}")
            print("No completed tickets found.")
            print("---")

def main():
    current_year = datetime.now().year
    start_date = f"{current_year}-01-01"
    end_date = f"{current_year}-12-31"
    calculate_monthly_average_cycle_time(start_date, end_date)

if __name__ == "__main__":
    main()