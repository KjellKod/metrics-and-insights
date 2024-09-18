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
    jql_query = f"project IN (ENG, ONF) AND summary ~ 'Production Release' AND type = 'Release' AND created  >= '{start_date}' AND created <= '{end_date}' ORDER BY created ASC"
    return jira.search_issues(jql_query, maxResults=1000, expand='changelog')

def extract_linked_tickets(issue):
    linked_keys = []
    for link in issue.fields.issuelinks:
        if hasattr(link, "outwardIssue"):
            linked_keys.append(link.outwardIssue.key)
    return linked_keys


def count_failed_releases(issue):
    release_events = []
    last_released_index = None

    # Reverse the order of histories to process from oldest to most recent
    for history in reversed(issue.changelog.histories):
        for item in history.items:
            if item.field == "status":
                if item.toString == "Released":
                    release_date = datetime.strptime(history.created, "%Y-%m-%dT%H:%M:%S.%f%z")
                    release_events.append((release_date, False))
                    last_released_index = len(release_events) - 1
                if item.fromString == "Released" and item.toString != "Released":
                    if last_released_index is not None:
                        release_events[last_released_index] = (release_events[last_released_index][0], True)
                        last_released_index = None  # Reset the index after marking as failed

    fail_count = sum(1 for _, failed in release_events if failed)
    return fail_count, release_events


def analyze_release_tickets(start_date, end_date):
    release_tickets = get_release_tickets(start_date, end_date)
    release_info = defaultdict(list)
    failed_releases_per_month = defaultdict(int)
    failed_releaselinked_tickets_count_per_month = defaultdict(int)  # To store the total linked tickets considering multiple failures
    total_linked_tickets_count_per_month =  defaultdict(int)
    total_releases_per_month = defaultdict(int) 

    for ticket in release_tickets:
        linked_tickets = extract_linked_tickets(ticket)
        fail_count, release_events = count_failed_releases(ticket)
        
        # Sort release events by date
        release_events.sort(key=lambda x: x[0])
        
        for release_date, failed in release_events:
            month_key = release_date.strftime("%Y-%m")
            release_info[month_key].append({
                "release_ticket": ticket.key,
                "release_date": release_date.strftime("%Y-%m-%d"),
                "linked_tickets": linked_tickets,
                "failed": failed
            })
            total_releases_per_month[month_key] += 1  # Increment total releases for the month
            total_linked_tickets_count_per_month[month_key] += len(linked_tickets)  # Increment total linked tickets for the month
            if failed:
                failed_releases_per_month[month_key] += 1
                failed_releaselinked_tickets_count_per_month[month_key] += len(linked_tickets)

    # Print the collected information
    for month in sorted(release_info.keys()):
        print(f"Month: {month}")
        for info in sorted(release_info[month], key=lambda x: x['release_date']):
            fail_message = "FAILED RELEASE  " if info['failed'] else "\t\t"
            print(f"{fail_message} {info['release_ticket']} [{info['release_date']}], Linked Tickets: {len(info['linked_tickets'])} ({', '.join(info['linked_tickets'])})")
        total_releases = total_releases_per_month[month]
        failed_releases = failed_releases_per_month[month]
        failure_percentage = (failed_releases / total_releases) * 100 if total_releases > 0 else 0
        print(f"Total of {total_releases} releases for {month}, number of failed: {failed_releases}")
        print(f"Total released tickets {total_linked_tickets_count_per_month[month]}, total failed release linked tickets: {failed_releaselinked_tickets_count_per_month[month]}") 
        print(f"Release Failure Percentage for {month}: {failure_percentage:.2f}%")
        print(f"Release Failure Linked Tickets Percentage for {month}: {(failed_releaselinked_tickets_count_per_month[month] / total_linked_tickets_count_per_month[month]) * 100:.2f}%")
        print("---")

    # Calculate and print the total release failure percentage for the whole time period
    total_releases_all_time = sum(total_releases_per_month.values())
    total_failed_releases_all_time = sum(failed_releases_per_month.values())
    total_failure_percentage = (total_failed_releases_all_time / total_releases_all_time) * 100 if total_releases_all_time > 0 else 0
    print(f"\nTotal release failure percentage for the whole time period: {total_failure_percentage:.2f}%")

def main():
    current_year = datetime.now().year
    start_date = f"{current_year}-01-01"
    end_date = f"{current_year}-12-31"
    analyze_release_tickets(start_date, end_date)

if __name__ == "__main__":
    main()
