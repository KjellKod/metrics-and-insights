from datetime import datetime
import os
from jira import JIRA
from collections import defaultdict

# Jira API endpoint
username = os.environ.get('USER_EMAIL')
api_key = os.environ.get('JIRA_API_KEY')
jira_url = os.environ.get('JIRA_LINK')

required_env_vars = ["JIRA_API_KEY", "USER_EMAIL", "JIRA_LINK"]

# JQL query
#jql_query = 'project = ENG AND issueType = Release AND created > "2024-01-01" AND status = "Released" ORDER BY updated DESC'

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




def print_engineering_excellence(): 
    jira = get_jira_instance()
    current_year = datetime.now().year
    start_date = f"{current_year}-01-01"
    end_date = f"{current_year}-12-31"

    jql_query = f"(project = ENG OR project = ONF) AND status = Done AND resolutiondate >= {start_date} AND resolutiondate <= {end_date} ORDER BY resolutiondate ASC"
    issues = jira.search_issues(jql_query, maxResults=None)
    month_data = defaultdict(lambda: {"engineering_excellence": 0, "other": 0})

    for issue in issues:
        resolution_date = datetime.strptime(issue.fields.resolutiondate, "%Y-%m-%dT%H:%M:%S.%f%z")
        month_key = resolution_date.strftime("%Y-%m")

        engineering_excellence = issue.fields.customfield_10079
        if engineering_excellence in ["Debt Reduction", "Critical"]:
            month_data[month_key]["engineering_excellence"] += 1
        else:
            month_data[month_key]["other"] += 1

    for month, data in sorted(month_data.items()):
        total_tickets = data["engineering_excellence"] + data["other"]
        percentage = (data["engineering_excellence"] / total_tickets) * 100 if total_tickets > 0 else 0
        print(f"Month: {month}")
        print(f"Engineering Excellence Tickets: {data['engineering_excellence']}")
        print(f"Other Tickets: {data['other']}")
        print(f"Percentage of Engineering Excellence Work: {percentage:.2f}%")
        print("---")

print_engineering_excellence()
    
    