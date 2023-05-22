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


# def find_squadcast_reopened_tickets(jira, issues):
#     reopened_tickets = []

#     for issue in issues:
#         issue_changelog = jira.issue(issue.key, expand="changelog")
#         histories = issue_changelog.changelog.histories

#         sorted_histories = sorted(
#             histories, key=lambda history: parse_date(history.created)
#         )

#         for history in sorted_histories:
#             for item in history.items:
#                 if item.field == "status" and history.author.displayName == "Squadcast":
#                     if item.fromString == "Closed":
#                         one_liner = (
#                             f"{history.author.displayName} moved ticket from "
#                             f"{item.fromString} to {item.toString} at {parse_date(history.created)}"
#                         )

#                         reopened_ticket_data = {
#                             "ID": issue.key,
#                             "Summary": issue.fields.summary,
#                             "StatusChange": one_liner,
#                         }

#                         reopened_tickets.append(reopened_ticket_data)

#     return reopened_tickets


def find_squadcast_reopened_tickets(jira, issues):
    reopened_tickets = []

    print(f" number of issues that we are parsing: {len(issues)}")

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
                    print(
                        f"ID {issue.key} change_author: {history.author.displayName} from {item.fromString} to {item.toString}"
                    )

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


def main():
    # Authenticate with JIRA API
    user = os.environ.get("USER_EMAIL")
    api_key = os.environ.get("JIRA_API_KEY")
    link = os.environ.get("JIRA_LINK")
    options = {
        "server": link,
    }
    jira = JIRA(options=options, basic_auth=(user, api_key))
    # (Key = 'GAN-202' OR Key = 'GAN-3192')
    # jql = f"project = GAN and Key = 'GAN-202' and (type = 'Story' OR type = 'Task') AND created < '2021-01-01' AND Status != \"Closed\" ORDER BY duedate ASC"

    jql = (
        "project = GAN AND type = 'Story' "
        "AND created >='2020-11-10' AND created < '2021-11-15'AND Status != 'Closed' ORDER BY duedate ASC"
    )

    issues = jira.search_issues(jql)
    # Find Squadcast Re-opened Tickets
    reopened_tickets = find_squadcast_reopened_tickets(jira, issues)
    print("Reopened Tickets:")
    for ticket in reopened_tickets:
        print(f"{ticket['ID']}\t {ticket['Summary']} \n\t{ticket['StatusChange']}")
        print("")


if __name__ == "__main__":
    main()
