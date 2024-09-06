from datetime import datetime
import os
from jira import JIRA
from collections import defaultdict
import json

# Jira API endpoint
username = os.environ.get('USER_EMAIL')
api_key = os.environ.get('JIRA_API_KEY')
jira_url = os.environ.get('JIRA_LINK')

required_env_vars = ["JIRA_API_KEY", "USER_EMAIL", "JIRA_LINK"]
for var in required_env_vars:    
    if os.environ.get(var) is None:
        raise ValueError(f"Environment variable {var} is not set.")

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



def get_resolution_date(ticket):
    for history in reversed(ticket.changelog.histories):
        for item in history.items:
            if item.field == "status" and item.toString == "Released":
                return datetime.strptime(history.created, "%Y-%m-%dT%H:%M:%S.%f%z")
    return None

def print_engineering_excellence(): 
    jira = get_jira_instance()
    current_year = datetime.now().year
    start_date = f"{current_year}-09-01"
    end_date = f"{current_year}-12-31"

    # Modified JQL query to filter tickets that changed to "Released" status within the given timeframe
    jql_query = f"project in (ONF, ENG, MOB) AND status changed to Released during ({start_date}, {end_date}) AND issueType in (Task, Bug, Story, Spike) ORDER BY updated ASC"

    print(jql_query) 

    released_tickets = jira.search_issues(jql_query, maxResults=1000, expand='changelog')
    team_data = defaultdict(lambda: defaultdict(lambda: {"engineering_excellence": 0, "other": 0}))
    print(f"Total number of tickets retrieved: {len(released_tickets)}")

    for ticket in released_tickets:
        resolution_date = get_resolution_date(ticket)
        if not resolution_date:
            print(f"Ticket {ticket.key} has no resolution date")
            continue
        month_key = resolution_date.strftime("%Y-%m")
        work_type = ticket.fields.customfield_10079
        team_field = ticket.fields.customfield_10075

        if ticket.fields.project.key == "MOB":
            team = "mobile"
        elif team_field is not None:
            team = team_field.value.strip()
        else:
            team = "unknown"

        if work_type is not None:
            work_type_value = work_type.value.strip()
        else:
            work_type_value = "Other"

        if work_type_value in ["Debt Reduction", "Critical"]:
            team_data[team][month_key]["engineering_excellence"] += 1
            #print(f"{ticket.key} - {work_type_value} - {team}")
        else:
            team_data[team][month_key]["other"] += 1
            #print(f"{month_key} {ticket.key} - {work_type_value} - {team}")

    for team, months in sorted(team_data.items()):
        print(f"Team {team.capitalize()}")
        for month, data in sorted(months.items()):
            total_tickets = data["engineering_excellence"] + data["other"]
            if total_tickets > 0:
                product_focus_percent = (data["other"] / total_tickets) * 100
                engineering_excellence_percent = (data["engineering_excellence"] / total_tickets) * 100
            else:
                product_focus_percent = 0
                engineering_excellence_percent = 0

            print(f"  {month} Total tickets: {total_tickets}, product focus: {data['other']} [{product_focus_percent:.2f}%], engineering excellence: {data['engineering_excellence']} [{engineering_excellence_percent:.2f}%]")



print_engineering_excellence()
    
    