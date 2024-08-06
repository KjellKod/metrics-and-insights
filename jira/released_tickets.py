import os
from jira import JIRA
from collections import defaultdict
from datetime import datetime

# Jira API endpoint
username = os.environ.get('USER_EMAIL')
api_key = os.environ.get('JIRA_API_KEY')
jira_url = os.environ.get('JIRA_LINK')

required_env_vars = ["JIRA_API_KEY", "USER_EMAIL", "JIRA_LINK"]
for var in required_env_vars:    
    if os.environ.get(var) is None:
        raise ValueError(f"Environment variable {var} is not set.")

# JQL query
current_year = datetime.now().year
start_date = f"{current_year}-01-01"
end_date = f"{current_year}-12-31"



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



def search_issues(jql):
    start_at = 0
    max_results = 100
    total_issues = []

    while True:
        pagination_issues = jira.search_issues(jql, startAt=start_at, maxResults=max_results)
        print(f"Received {len(pagination_issues)} tickets")
        total_issues.extend(pagination_issues)
        
        if len(pagination_issues) < max_results:
            break
        
        start_at += max_results

    print(f"Received a total of {len(total_issues)} tickets")
    return total_issues

def process_issues(issues):
    month_data = defaultdict(lambda: {"released_tickets_count": 0, "released_tickets": []})

    for issue in issues:
        updated_date = datetime.strptime(issue.fields.updated, "%Y-%m-%dT%H:%M:%S.%f%z")
        month_key = updated_date.strftime("%Y-%m")
        issue_key = issue.key
        
        month_data[month_key]["released_tickets_count"] += 1
        month_data[month_key]["released_tickets"].append(f"{issue_key}")

    return month_data



# Get the Jira instance
jira = get_jira_instance()
jql_query = f"project in (ONF, ENG, MOB) AND status in (Released) and (updatedDate >= 2024-01-01 and updatedDate <= 2024-12-31) AND issueType in (Task, Bug, Story, Spike) ORDER BY updated ASC"

# Run the JQL queries
jql_issues = search_issues(jql_query)

# Process the issues
jql_month_data = process_issues(jql_issues)

# Output the data in comma-separated format
print("\nJQL Query Results:")
for month, data in jql_month_data.items():
    print(f"\nMonth: {month}")
    print(f"Released Tickets Count: {data['released_tickets_count']}")
    print(f"Released Tickets: {', '.join(data['released_tickets'])}")
