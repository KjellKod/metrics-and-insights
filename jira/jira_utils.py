import os
from jira import JIRA
from jira.resources import Issue


def get_jira_instance():
    """
    Create the jira instance
    An easy way to set up your environment variables is through your .zshrc or .bashrc file
    export USER_EMAIL="your_email@example.com"
    export JIRA_API_KEY="your_jira_api_key"
    export JIRA_LINK="https://your_jira_instance.atlassian.net"
    """

    required_env_vars = ["JIRA_API_KEY", "USER_EMAIL", "JIRA_LINK", "JIRA_PROJECTS"]
    for var in required_env_vars:
        if os.environ.get(var) is None:
            raise ValueError(f"Environment variable {var} is not set.")

    user = os.environ.get("USER_EMAIL")
    api_key = os.environ.get("JIRA_API_KEY")
    link = os.environ.get("JIRA_LINK")
    options = {
        "server": link,
    }
    jira = JIRA(options=options, basic_auth=(user, api_key))
    return jira


def get_tickets_from_jira(jql_query):
    # Get the Jira instance
    jira = get_jira_instance()
    print(f"jql: {jql_query}")

    max_results = 100
    start_at = 0
    total_tickets = []

    while True:
        tickets = jira.search_issues(
            jql_query, startAt=start_at, maxResults=max_results, expand="changelog"
        )
        if len(tickets) == 0:
            break
        print(f"Received {len(tickets)} tickets")
        total_tickets.extend(tickets)
        start_at += max_results
        if len(tickets) < max_results:
            break
        start_at += max_results
    return total_tickets


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
