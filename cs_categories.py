import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

import numpy as np
from jira import JIRA
from jira.resources import Issue

from jira_file_utils import (
    export_tickets_per_label_csv,
    export_in_progress_time_per_label_csv,
    save_jira_data_to_file,
    load_jira_data_from_file,
)

from jira_time_utils import (
    datetime_serializer,
    get_resolution_date,
    DateTimeEncoder,
    parse_date,
    seconds_to_hms,
    business_time_spent_in_seconds,
)

from jira_content_utility import (
    g_status_list,
    parse_status_changes,
    calculate_status_intervals,
    find_status_timestamps,
    save_status_timing_results,
    extract_status_durations,
    get_custom_fields_mapping,
    extract_ticket_data,
    process_issues,
    extract_closed_date,
    update_aggregated_results,
)


def print_time_records(label, time_records):
    print(f'Label: {label} {time_records["total_tickets"]} tickets completed')
    print(f"\tTotal In Progress   (m): {time_records['total_in_progress_s']/60:7.2f}")
    print(f"\tTotal In Review     (m): {time_records['total_in_review_s']/60:7.2f}")
    print(f"\tAverage In Progress (m): {time_records['average_in_progress_s']/60:7.2f}")
    print(f"\tAverage In Review   (m): {time_records['average_in_review_s']/60:7.2f}")
    print()


def print_detailed_ticket_data(ticket_data):
    # Assuming you have `ticket_data` object
    pretty_ticket_data = json.dumps(ticket_data, indent=4, default=datetime_serializer)
    print(pretty_ticket_data)

    for key, ticket in ticket_data.items():
        in_progress_duration = ticket["in_progress_s"]
        in_progress_hms = seconds_to_hms(in_progress_duration)
        in_progress_str = f"{in_progress_hms[0]} hours, {in_progress_hms[1]} minutes, {in_progress_hms[2]} seconds"
        print(
            f'ticket {key}, closing_date: {ticket["resolutiondate"]}, in_progress: {in_progress_duration}s [{in_progress_str}]'
        )


# Fetch all issues with specific label
def fetch_issues_by_label(jira, label, resolution_date):
    issues = []
    start_index = 0
    max_results = 100

    query = (
        f"project = GAN  AND status in (Closed) "
        f'and labels="{label}" '
        f'and resolution NOT IN ("Duplicate", "Won\'t Do", "Declined") '
        f"and resolutiondate > '{resolution_date}' "
        f"order by resolved desc"
    )

    print(f" Executing query:\n\t [{query}]")

    while True:
        chunk = jira.search_issues(
            jql_str=query.format(label=label),
            startAt=start_index,
            maxResults=max_results,
            expand="changelog",
        )

        if len(chunk) == 0:
            break

        issues.extend(chunk)
        start_index += max_results

    return issues


def retrieve_jira_query_issues(args, jira, label, resolution_date):
    issues = {}
    jira_file = f"xops_data/{label}_data.json"
    if args.load:
        jira_file = f"xops_data/{label}_data.json"
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
        issues = fetch_issues_by_label(jira, label, resolution_date)
        print(f'Fetched {len(issues)} issues with label "{label}"...')

    if args.save:
        print(f"Saving JIRA {len(issues)} issues to {jira_file}")
        save_jira_data_to_file(issues, jira_file)
    return issues


# ... (Imports and other functions here)


def parse_arguments():
    parser = argparse.ArgumentParser(description="Query with custom timeframe.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Display detailed ticket data")
    parser.add_argument(
        "-l",
        "--load",
        action="store_true",
        help="Load from previously stored json dump of JIRA data",
    )
    parser.add_argument(
        "-s",
        "--save",
        action="store_true",
        help="Save a json dump from the JIRA data you will now retrieve, you can later use the -l --load function and avoid JIRA query overhead",
    )

    parser.add_argument(
        "--resolution-date",
        type=str,
        metavar="YYYY-MM-DD",
        help="Enter a specific resolution date in YYYY-MM-DD format",
    )

    parser.add_argument(
        "--weeks-back",
        type=int,
        help="Enter how many weeks back from today to set the resolution date",
    )

    # Parse the arguments
    args = parser.parse_args()

    # Get the resolution date parameter
    if args.resolution_date:
        resolution_date = args.resolution_date
    elif args.weeks_back:
        resolution_date = get_resolution_date(args.weeks_back)
    else:
        parser.print_help()
        exit(1)

    return args, resolution_date


# # https://ganazhq.slack.com/archives/C03BR47GDQW/p1684342201816599
# # https://ganaz.atlassian.net/browse/GAN-5750
def main():
    args, resolution_date = parse_arguments()

    xops_labels = [
        "xops_packet_update",
        "xops_new_packet",
        "xops_ch_sms_whatsapp",
        "xops_ch_change_name",
        "xops_ch_message_troubleshoot",
        "xops_enable_remittances",
        "xops_remove_profile",
        "xops_ch_portal",
        "xops_company_employee_id_counter",
        "xops_raffle",
        "xops_reports",
        "xops_carholder_assorted",
        "xops_remove_incomplete_packets" "xops_new_packet",
        "xops_training_tracks",
        "xops_paystubs",
    ]

    default_metrics = {
        "tickets_completed": 0,
        "total_in_progress": 0,
        "total_in_review": 0,
        "average_in_progress": 0,
        "average_in_review": 0,
    }

    # Generate data list from xops_labels and default_metrics
    data = {label: dict(default_metrics) for label in xops_labels}

    # Perform JQL query and handle pagination if needed
    user = os.environ.get("USER_EMAIL")
    api_key = os.environ.get("JIRA_API_KEY")
    link = os.environ.get("JIRA_LINK")
    options = {
        "server": link,
    }
    jira = JIRA(options=options, basic_auth=(user, api_key))
    custom_fields_map = get_custom_fields_mapping(jira)

    # Loop through each xops_label, fetch issues and process results
    xops_time_records = {}
    for label in xops_labels:
        issues = retrieve_jira_query_issues(args, jira, label, resolution_date)
        print(f'Processing {len(issues)} issues with label "{label}"...')
        ticket_data = process_issues(jira, issues, custom_fields_map)

        if args.verbose:
            print_detailed_ticket_data(ticket_data)

        time_records = update_aggregated_results(xops_time_records, ticket_data, label)
        data[label] = time_records[label]
        print(f"total tickets: {len(ticket_data)}")

    # Convert data dictionary into list of dicts
    data_list = [{**{"label": label}, **values} for label, values in data.items()]
    # Sort and print the records
    sorted_data = sorted(data_list, key=lambda x: x["total_tickets"], reverse=True)

    for item in sorted_data:
        print(f"Label: {item['label']} {item['total_tickets']} tickets completed")
        print(f"\tTotal In Progress   (m): {item['total_in_progress']/60:>7.2f}")
        print(f"\tTotal In Review     (m): {item['total_in_review']/60:>7.2f}")
        print(f"\tAverage In Progress (m): {item['average_in_progress']/60:>7.2f}")
        print(f"\tAverage In Review   (m): {item['average_in_review']/60:>7.2f}\n")

        # Convert data dictionary into list of tuples for export functions
    # [("label1", 10), ("label2", 15), ...]
    data_list_1 = [(label, values["total_tickets"]) for label, values in data.items()]
    data_list_1.sort(key=lambda x: x[1], reverse=True)

    # [("label1", 3600), ("label2", 1800), ...]
    data_list_2 = [(label, values["total_in_progress"]) for label, values in data.items()]
    data_list_2.sort(key=lambda x: x[1], reverse=True)

    # Export two separate CSV files
    # Export the two CSV files
    resolution_date_formatted = f"{resolution_date}"

    # Export the two CSV files with the formatted titles
    export_tickets_per_label_csv(
        data_list_1,
        "xops_data/tickets_per_label.csv",
        f"xops tickets since {resolution_date_formatted}",
    )
    export_in_progress_time_per_label_csv(
        data_list_2,
        "xops_data/in_progress_time_per_label.csv",
        f"xops time, in-progress, since {resolution_date_formatted}",
    )


if __name__ == "__main__":
    main()
