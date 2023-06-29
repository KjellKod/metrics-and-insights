import os
import csv
import json
from jira import JIRA
from jira.resources import Issue


def export_tickets_per_label_csv(data, filename, title):
    with open(filename, mode="w", newline="") as csvfile:
        writer = csv.writer(csvfile)

        # Write a title (timeframe)
        writer.writerow([title])

        # Add the headers
        writer.writerow(["label", "total_tickets"])

        # Add the data
        for row in data:
            label, total_tickets = row
            writer.writerow([label, total_tickets])

    print(f"CSV file {filename} has been generated with 'label' and 'total_tickets' columns.")


def export_in_progress_time_per_label_csv(data, filename, title):
    with open(filename, mode="w", newline="") as csvfile:
        writer = csv.writer(csvfile)

        # Write a title (timeframe)
        writer.writerow([title])

        # Add the headers
        writer.writerow(["label", "total_in_progress"])

        # Add the data
        for row in data:
            label, total_in_progress = row
            writer.writerow([label, total_in_progress])

    print(f"CSV file {filename} has been generated with 'label' and 'total_in_progress' columns.")


def save_jira_data_to_file(data, file_name):
    with open(file_name, "w") as outfile:
        json.dump([issue.raw for issue in data], outfile)


def load_jira_data_from_file(file_name, jira_instance):
    with open(f"{file_name}", "r") as infile:
        raw_issues_data = json.load(infile)

    issues = [Issue(jira_instance._options, jira_instance._session, raw) for raw in raw_issues_data]
    return issues


def fetch_issues_from_api(jira, query):
    issues = []
    start_index = 0
    max_results = 100

    print(f" Executing query:\n\t [{query}]")

    while True:
        chunk = jira.search_issues(
            jql_str=query,
            startAt=start_index,
            maxResults=max_results,
            expand="changelog",
        )

        if len(chunk) == 0:
            break

        issues.extend(chunk)
        start_index += max_results

    return issues


def retrieve_jira_issues(args, jira, query, tag, path):
    issues = {}
    jira_file = f"{path}/{tag}_data.json"
    if args.load:
        jira_file = f"{path}/{tag}_data.json"
        if not os.path.exists(jira_file):
            print(
                f"\nWARNING {jira_file} does not exist. The data is missing, or you need to retrieve JIRA data first and save it with the '-s' option first.\n"
            )
            return []  # Return an empty list or handle the error accordingly
        issues = load_jira_data_from_file(jira_file, jira)
        if issues is None:
            print("Failed to load JIRA data from file")
            return []  # Return an empty list or handle the error accordingly
        print(f"Load jira {len(issues)} tickets from {jira_file}")
    else:
        issues = fetch_issues_from_api(jira, query)
        print(f'Fetched {len(issues)} issues for  "{tag}"...')

    if args.save:
        print(f"Saving JIRA {len(issues)} issues to {jira_file}")
        save_jira_data_to_file(issues, jira_file)
    return issues
