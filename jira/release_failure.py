import os
from jira import JIRA
from collections import defaultdict
from datetime import datetime

# Setup JIRA connection
def get_jira_instance():
    options = {"server": os.environ.get("JIRA_LINK")}
    jira = JIRA(options=options, basic_auth=(os.environ.get("USER_EMAIL"), os.environ.get("JIRA_API_KEY")))
    return jira

def get_release_tickets(start_date, end_date):
    jira = get_jira_instance()
    # Adjust the JQL query to focus on release tickets
    jql_query = f"project = ENG AND summary ~ 'Production Release' AND created >= '{start_date}' AND created <= '{end_date}' AND status = 'Released' ORDER BY created ASC"
    return jira.search_issues(jql_query, maxResults=1000)

def extract_linked_tickets(issue):
    linked_keys = []
    for link in issue.fields.issuelinks:
        if hasattr(link, "outwardIssue"):
            linked_keys.append(link.outwardIssue.key)
        elif hasattr(link, "inwardIssue"):
            linked_keys.append(link.inwardIssue.key)
    return linked_keys

def analyze_release_tickets(start_date, end_date):
    release_tickets = get_release_tickets(start_date, end_date)
    release_info = defaultdict(list)
    linked_tickets_count_per_month = defaultdict(int)

    for ticket in release_tickets:
        month_key = datetime.strptime(ticket.fields.created, "%Y-%m-%dT%H:%M:%S.%f%z").strftime("%Y-%m")
        linked_tickets = extract_linked_tickets(ticket)
        release_info[month_key].append({
            "release_ticket": ticket.key,
            "linked_tickets": linked_tickets
        })
        linked_tickets_count_per_month[month_key] += len(linked_tickets)

    # Print the collected information
    for month, tickets in release_info.items():
        print(f"Month: {month}")
        for info in tickets:
            print(f"Release Ticket: {info['release_ticket']}, Linked Tickets: {len(info['linked_tickets'])} ({', '.join(info['linked_tickets'])})")
        print(f"Total Linked Tickets for {month}: {linked_tickets_count_per_month[month]}")
        print("---")

def main():
    current_year = datetime.now().year
    start_date = f"{current_year}-01-01"
    end_date = f"{current_year}-12-31"
    analyze_release_tickets(start_date, end_date)

if __name__ == "__main__":
    main()
