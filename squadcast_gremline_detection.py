import os
from jira import JIRA
from datetime import datetime, date, timedelta
import numpy as np


def custom_serializer(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    elif isinstance(obj, np.int64):
        return int(obj)
    else:
        try:
            # Try to convert the object to a dictionary, if possible
            serializable_obj = vars(obj)
            return serializable_obj
        except TypeError:
            raise TypeError(
                f"Object of type {obj.__class__.__name__} is not JSON serializable"
            )


def parse_date(date_str):
    if date_str is not None:
        return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S.%f%z")
    return None


def find_squadcast_reopened_tickets(jira, issues):
    reopened_tickets = []
    for issue in issues:
        issue_changelog = jira.issue(issue.key, expand="changelog")
        histories = issue_changelog.changelog.histories

        # print(f" {issue.key}")
        sorted_histories = sorted(
            histories, key=lambda history: parse_date(history.created)
        )

        for history in sorted_histories:
            for item in history.items:
                if item.field == "status" and history.author.displayName == "Squadcast":
                    # print(
                    #     f"ID {issue.key} change_author: {history.author.displayName} from {item.fromString} to {item.toString}"
                    # )

                    if item.fromString == "Closed":
                        one_liner = (
                            f"{history.author.displayName} moved ticket from "
                            f"{item.fromString} to {item.toString} at {parse_date(history.created)}"
                        )

                        reopened_ticket_data = {
                            "ID": issue.key,
                            "Summary": issue.fields.summary,
                            "StatusChange": one_liner,
                        }

                        reopened_tickets.append(reopened_ticket_data)

    return reopened_tickets


import os
from jira import JIRA


def main():
    # Authenticate with JIRA API
    user = os.environ.get("USER_EMAIL")
    api_key = os.environ.get("JIRA_API_KEY")
    link = os.environ.get("JIRA_LINK")
    options = {
        "server": link,
    }
    jira = JIRA(options=options, basic_auth=(user, api_key))

    jql = (
        "project = GAN AND type = 'Story' "
        "AND created >='2020-01-01' AND Status != 'Closed' ORDER BY duedate ASC"
    )

    start_at = 0
    max_results = 50
    total_issues_processed = 0
    loop_counter = 1
    reopened_tickets_all = []

    while True:
        issues = jira.search_issues(
            jql,
            startAt=start_at,
            maxResults=max_results,
        )

        if not issues:
            # Break the loop if there are no more is∂çsues
            break

        # Process the issues in the current batch
        reopened_tickets = find_squadcast_reopened_tickets(jira, issues)
        reopened_tickets_all.append(reopened_tickets)

        # Print the results
        if reopened_tickets:
            print("Reopened Tickets:")
            for ticket in reopened_tickets:
                print(
                    f"{ticket['ID']}\t {ticket['Summary']} \n\t{ticket['StatusChange']}"
                )
                print("")

        total_issues_processed += len(issues)
        id_first = issues[0].key
        id_last = issues[-1].key
        created_first = issues[0].fields.created[:10]
        created_last = issues[-1].fields.created[:10]

        print(
            f"Parsing {len(issues)} issues: From {id_first} ({created_first}) to {id_last} ({created_last})"
        )
        print(
            f"Processed {total_issues_processed} issues out of {total_issues_processed + len(issues)}"
        )

        start_at += max_results
        loop_counter += 1

    print("Final Result - All Reopened Ticket IDs:")

    for reopened_tickets in reopened_tickets_all:
        for ticket in reopened_tickets:
            print(ticket["ID"])


if __name__ == "__main__":
    main()
