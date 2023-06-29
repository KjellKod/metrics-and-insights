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
