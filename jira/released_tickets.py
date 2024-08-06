import os
from jira import JIRA
from collections import defaultdict
from datetime import datetime

# Jira API endpoint
username = os.environ.get('USER_EMAIL')
api_key = os.environ.get('JIRA_API_KEY')
jira_url = os.environ.get('JIRA_LINK')

required_env_vars = ["JIRA_API_KEY", "USER_EMAIL", "JIRA_LINK"]

# JQL query
current_year = datetime.now().year
start_date = f"{current_year}-01-01"
end_date = f"{current_year}-12-31"

jql_query = f"(project=MOB OR project=ENG OR project=ONF) AND resolutiondate >= {start_date} AND resolutiondate <= {end_date} AND issueType in ('Task', 'Bug', 'Story', 'Spike') AND status in ('Done', 'Closed', 'Released') AND status != \"Won't Do\" ORDER BY resolutiondate ASC"
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

# Get the Jira instance
jira = get_jira_instance()

# Perform the JQL query using the Jira instance
issues = jira.search_issues(jql_query, maxResults=None)
month_data = defaultdict(lambda: {"released_tickets_count": 0, "released_tickets": []})

for issue in issues:
    resolution_date = datetime.strptime(issue.fields.resolutiondate, "%Y-%m-%dT%H:%M:%S.%f%z")
    month_key = resolution_date.strftime("%Y-%m")
    issue_key = issue.key

    
    # Extract the month from the issue's created date
    resolution_date = datetime.strptime(issue.fields.resolutiondate, "%Y-%m-%dT%H:%M:%S.%f%z")
    month_key = resolution_date.strftime("%Y-%m")
    
    month_data[month_key]["released_tickets_count"] += 1
    month_data[month_key]["released_tickets"].append(f"{issue_key}")

# Group issues by month and count linked tickets
# month_data = defaultdict(lambda: {"released_tickets": 0, "releases": []})
# for issue in issues:
#     issue_key = issue.key
#     issue_title = issue.fields.summary
#     issue_links = issue.fields.issuelinks
#     linked_issues_count = len(issue_links)
    
#     # Extract the month from the release title
#     release_month = issue_title.split(" ")[-1][:7]
    
#     month_data[release_month]["released_tickets"] += linked_issues_count
#     month_data[release_month]["releases"].append(f"{issue_key}, {issue_title}, released tickets: {linked_issues_count}")

# # Output in human-readable format
# print("Individual Release Details:")
# for issue in issues:
#     issue_key = issue.key
#     issue_title = issue.fields.summary
#     issue_links = issue.fields.issuelinks
#     linked_issues_count = len(issue_links)
    
#     print(f"{issue_key}, {issue_title}, released tickets: {linked_issues_count}")

print("\n")

# Output the data in comma-separated format
for month, data in month_data.items():
    print ("\n\n")
    print(f"Month: {month}")
    print(f"Released Tickets Count: {data['released_tickets_count']}")
    print(f"Released Tickets: {data['released_tickets']}")
    print()
