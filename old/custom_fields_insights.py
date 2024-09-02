
import os
import json
from jira import JIRA
from common.jira_time_utils import parse_date


def fetch_tickets(jira, project, team, sprint, work_type):
    """
    Fetch Debt Reduction tickets from the specified project, team, and sprint.
    """
    jql_query = (
        f"project = {project} "
        f"AND Sprint = '{sprint}' "
        f"AND \"Team[Dropdown]\" in ('{team}') "
        f"AND {work_type} "
        f"AND status in (Released, Done, Closed, 'TO RELEASE') "
    )
    issues = jira.search_issues(jql_query, maxResults=-1)
    return issues

def print_tickets(issues):
    """
    Print the retrieved tickets.
    """

    for issue in issues:
        engineering_excellence = issue.fields.customfield_10079

        print(issue.fields)
        print(f"Key: {issue.key}")
        print(f"Summary: {issue.fields.summary}")
        print(f"Status: {issue.fields.status.name}")
        print(f"Resolution: {issue.fields.resolution.name if issue.fields.resolution else 'N/A'}")
        #print(f"Resolution Date: {parse_date(issue.fields.resolutiondate)}")
        print(f"Resolution Date: {issue.fields.resolutiondate}")
        print(f"Work Type: {engineering_excellence}")
        print("++++++++++++++++++++++++")


def get_engineering_excellence_search_string():
    return "'Work Type' in ('Debt Reduction', 'Critical') "


def calculate_engineering_excellence_percentage(eng_excellence_tickets, non_eng_excellence_tickets):
    """
    Calculate the percentage of completed Engineering Excellence tickets.
    """
    total_tickets = len(eng_excellence_tickets) + len(non_eng_excellence_tickets)
    eng_excellence_tickets_count = len(eng_excellence_tickets)
    percentage = (eng_excellence_tickets_count / total_tickets) * 100
    return percentage


def get_jira_instance():
    """
    Create the Jira instance using environment variables.
    """
    user = os.environ.get("USER_EMAIL")
    api_key = os.environ.get("JIRA_API_KEY")
    link = os.environ.get("JIRA_LINK")
    options = {
        "server": link,
    }
    jira = JIRA(options=options, basic_auth=(user, api_key))
    return jira

def main():
    """
    Main function to fetch and print Debt Reduction tickets.
    """
    project = "ONF"
    team = "Spork"
    sprint = "2024-Q2-S3-Spork"

    jira = get_jira_instance()
    issuesEE = fetch_tickets(jira, project, team, sprint, get_engineering_excellence_search_string())
    issues = fetch_tickets(jira, project, team, sprint, " NOT " + get_engineering_excellence_search_string())

    print_tickets(issuesEE)
    print(f"Retrieved {len(issuesEE)} Debt Reduction tickets.")
    print(f"Retrieved {len(issues) + len(issuesEE)} Total tickets")
    print(f"Percentage completed EE work round({calculate_engineering_excellence_percentage(issuesEE, issues):.2f})")


if __name__ == "__main__":
    main()