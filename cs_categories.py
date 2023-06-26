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

g_status_list = ["In Progress", "In Review", "Pending Release"]

import csv


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

    print(
        f"CSV file {filename} has been generated with 'label' and 'total_tickets' columns."
    )


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

    print(
        f"CSV file {filename} has been generated with 'label' and 'total_in_progress' columns."
    )


def save_jira_data_to_file(data, file_name):
    with open(file_name, "w") as outfile:
        json.dump([issue.raw for issue in data], outfile)


def load_jira_data_from_file(file_name, jira_instance):
    with open(f"{file_name}", "r") as infile:
        raw_issues_data = json.load(infile)

    issues = [
        Issue(jira_instance._options, jira_instance._session, raw)
        for raw in raw_issues_data
    ]
    return issues


def datetime_serializer(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    elif isinstance(obj, np.int64):
        return int(obj)
    else:
        raise TypeError(
            f"Object of type {obj.__class__.__name__} is not JSON serializable"
        )


# Function to calculate resolution_date based on weeks_back input
def get_resolution_date(weeks_back):
    return (date.today() - timedelta(weeks=weeks_back)).strftime("%Y-%m-%d")


class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super(DateTimeEncoder, self).default(obj)


def parse_date(date_str):
    if date_str is not None:
        return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S.%f%z")
    return None


def seconds_to_hms(seconds):
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return hours, minutes, seconds


def business_time_spent_in_seconds(start, end):
    weekdays = [0, 1, 2, 3, 4]  # Monday to Friday
    total_business_seconds = 0
    seconds_in_workday = 8 * 60 * 60  # 8 hours * 60 minutes * 60 seconds

    current = start
    while current <= end:
        if current.weekday() in weekdays:
            day_end = current.replace(hour=23, minute=59)
            remaining_time_today = day_end - current

            if current.date() != end.date():
                total_business_seconds += min(
                    remaining_time_today.total_seconds(), seconds_in_workday
                )
                current += timedelta(days=1)
                current = current.replace(hour=0, minute=0)
            else:
                remaining_time_on_last_day = end - current
                total_business_seconds += min(
                    remaining_time_on_last_day.total_seconds(), seconds_in_workday
                )
                break
        else:
            current += timedelta(days=1)
            current = current.replace(hour=0, minute=0)

    return total_business_seconds


def parse_status_changes(histories):
    status_changes = []

    # Sort histories by created timestamp in ascending order (chronologically)
    sorted_histories = sorted(
        histories, key=lambda history: parse_date(history.created)
    )

    for history in sorted_histories:
        for item in history.items:
            if item.field == "status":
                status_changes.append(
                    {
                        "from": item.fromString,
                        "to": item.toString,
                        "timestamp": parse_date(history.created),
                    }
                )
    return status_changes


def calculate_status_intervals(status_changes, status_to_measure):
    status_intervals = []
    status_start = None

    for change in status_changes:
        if change["to"] == status_to_measure:
            status_start = change["timestamp"]
        elif status_start is not None and change["from"] == status_to_measure:
            status_end = change["timestamp"]
            interval = (
                status_to_measure,
                status_start,
                status_end,
            )  # Include state name
            status_intervals.append(interval)
            status_start = None

    return status_intervals


def find_status_timestamps(status_changes, *statuses):
    timestamps = {status: None for status in statuses}

    for change in status_changes:
        if change["to"] in statuses:
            if not timestamps[change["to"]]:  # Add this line
                timestamps[change["to"]] = change["timestamp"]

    return timestamps


def save_status_timing_results(result_dict, issue_key, status, intervals):
    if issue_key not in result_dict:
        result_dict[issue_key] = {}

    new_intervals = [
        {
            "start": start,
            "end": end,
            "duration_s": (end - start).total_seconds(),
            "adjusted_duration_s": business_time_spent_in_seconds(start, end),
        }
        for state, start, end in intervals
    ]

    if status not in result_dict[issue_key]:
        result_dict[issue_key][status] = new_intervals
    else:
        result_dict[issue_key][status].extend(new_intervals)


def extract_status_durations(jira, jira_issue, result_dict):
    issue = jira.issue(jira_issue.key, expand="changelog")

    status_changes = parse_status_changes(issue.changelog.histories)

    for status in g_status_list:
        intervals = calculate_status_intervals(status_changes, status)
        save_status_timing_results(result_dict, issue.key, status, intervals)

    for key, ticket in result_dict.items():
        in_progress_sum = sum(
            [
                interval["adjusted_duration_s"]
                for interval in ticket.get("In Progress", [])
            ]
        )
        in_review_sum = sum(
            [
                interval["adjusted_duration_s"]
                for interval in ticket.get("In Review", [])
            ]
        )
        ticket["in_progress_s"] = in_progress_sum
        ticket["in_review_s"] = in_review_sum


# Function to fetch custom fields and map them by ID
def get_custom_fields_mapping(jira):
    custom_field_map = {}
    fields = jira.fields()
    for field in fields:
        if field["custom"]:
            custom_field_map[field["id"]] = field["name"]

    return custom_field_map


# extract metadata with from the ticket
def extract_ticket_data(issue, custom_fields_map, result_dict):
    result_dict[issue.key] = {}
    result_dict[issue.key]["ID"] = issue.key
    result_dict[issue.key]["summary"] = issue.fields.summary
    result_dict[issue.key]["status"] = issue.fields.status.name
    result_dict[issue.key]["points"] = issue.fields.customfield_10028
    result_dict[issue.key]["sprint"] = issue.fields.customfield_10020
    result_dict[issue.key]["start"] = issue.fields.customfield_10015
    result_dict[issue.key]["resolutiondate"] = issue.fields.resolutiondate
    result_dict[issue.key]["description"] = issue.fields.description

    for field_id, field_value in issue.raw["fields"].items():
        # Get field name or use ID as fallback
        field_name = custom_fields_map.get(field_id, field_id)

        if field_value is None:
            value_str = "None"
        elif isinstance(field_value, (str, int, float)):
            value_str = str(field_value)
        # Add support for issuetype display
        if field_name == "issuetype":
            result_dict[issue.key]["type"] = field_value.get(
                "name", f"<class '{field_value.__class__.__name__}'>"
            )
            continue
        # Add support for assignee display -->  assignee (assignee): <class 'dict'>
        elif field_name == "assignee":
            result_dict[issue.key]["assignee"] = (
                field_value.get(
                    "displayName", f"<class '{field_value.__class__.__name__}'>"
                )
                if field_value
                else None
            )
            continue
        elif field_name == "resolution":
            if isinstance(field_value, dict):
                result_dict[issue.key]["resolution"] = field_value
            elif field_value is not None:
                result_dict[issue.key]["resolution"] = {"name": field_value}
            else:
                result_dict[issue.key]["resolution"] = None
        elif isinstance(field_value, dict) and "value" in field_value:
            value_str = str(field_value["value"])
        else:
            value_str = f"<class '{field_value.__class__.__name__}'>"

        if field_name == "components":
            result_dict[issue.key]["component"] = []
            for component in field_value:
                component_name = component["name"]
                result_dict[issue.key]["component"].append(component_name)


# Process issues to calculate In-Progress time, In-Review time, etc.
def process_issues(jira, issues, custom_fields_map):
    ticket_data = {}

    for issue in issues:
        extract_ticket_data(issue, custom_fields_map, ticket_data)
        extract_status_durations(jira, issue, ticket_data)

    return ticket_data


def extract_closed_date(ticket_data):
    closed_dates = defaultdict(dict)

    for key, ticket in ticket_data.items():
        for status in g_status_list:
            if ticket.get(status):
                closed_timestamp = ticket[status][-1]["end"]
                closed_time = closed_timestamp.strftime("%Y-%m-%d")
                closed_dates[status][key] = closed_time

    return closed_dates


def update_aggregated_results(xops_time_records, ticket_data, label):
    total_adjusted_in_progress_seconds = 0
    total_adjusted_in_review_seconds = 0
    total_tickets = len(ticket_data)

    for key, ticket in ticket_data.items():
        in_progress_intervals = ticket.get("In Progress", [])
        in_review_intervals = ticket.get("In Review", [])

        for interval in in_progress_intervals:
            adjusted_duration_s = interval["adjusted_duration_s"]
            total_adjusted_in_progress_seconds += adjusted_duration_s

        for interval in in_review_intervals:
            adjusted_duration_s = interval["adjusted_duration_s"]
            total_adjusted_in_review_seconds += adjusted_duration_s

    average_in_progress_s = (
        total_adjusted_in_progress_seconds / total_tickets if total_tickets > 0 else 0
    )
    average_in_review_s = (
        total_adjusted_in_review_seconds / total_tickets if total_tickets > 0 else 0
    )

    xops_time_records[label] = {
        "total_tickets": len(ticket_data),
        "total_in_progress": total_adjusted_in_progress_seconds,
        "total_in_review": total_adjusted_in_review_seconds,
        "average_in_progress": average_in_progress_s,
        "average_in_review": average_in_review_s,
        "total_tickets": total_tickets,
    }

    return xops_time_records


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
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Display detailed ticket data"
    )
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
# # xops_ch_sms_whatsapp
# # xops_ch_change_name
# # xops_ch_message_troubleshoot
# # xops_enable_remittances
# # xops_remove_profile
# # xops_packet_update
# # xops_new_packet
# # xops_ch_portal
# # xops_company_employee_id_counter
# # xops_raffle
# # xops_carholder_assorted
# # xops_remove_incomplete_packets
# # xops_new_packet -- NOT in-review but 'acceptance-testing' as end criterion
## xops_training_tracks
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
        "xops_remove_incomplete_packets"
        "xops_new_packet", 
        "xops_training_tracks" 
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
    data_list_2 = [
        (label, values["total_in_progress"]) for label, values in data.items()
    ]
    data_list_2.sort(key=lambda x: x[1], reverse=True)

    # Export two separate CSV files
    # Export the two CSV files
    resolution_date_formatted = f"{resolution_date}"

    # Export the two CSV files with the formatted titles
    export_tickets_per_label_csv(
        data_list_1,
        "tickets_per_label.csv",
        f"xops tickets since {resolution_date_formatted}",
    )
    export_in_progress_time_per_label_csv(
        data_list_2,
        "in_progress_time_per_label.csv",
        f"xops time, in-progress, since {resolution_date_formatted}",
    )


if __name__ == "__main__":
    main()
