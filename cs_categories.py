import os
from jira import JIRA
from jira.resources import Issue
import json
from datetime import datetime, date, timedelta
import numpy as np
from collections import defaultdict

g_in_progress_id = 0
g_in_review_id = 1
g_in_pending_release_id = 2

g_status_list = ["In Progress", "In Review", "Pending Release"]


def save_jira_data_to_file(data, file_name):
    with open(file_name, "w") as outfile:
        json.dump([issue.raw for issue in data], outfile)


def load_jira_data_from_file(file_name, jira_instance):
    with open(file_name, "r") as infile:
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

    xops_time_records[label] = {
        "total_tickets": len(ticket_data),
        "total_in_progress_s": total_adjusted_in_progress_seconds,
        "total_in_review_s": total_adjusted_in_review_seconds,
        "average_in_progress_s": (total_adjusted_in_progress_seconds / total_tickets),
        "average_in_review_s": (total_adjusted_in_review_seconds / total_tickets),
        "total_tickets": total_tickets,
    }

    return xops_time_records


def display_ticket_close_dates(ticket_close_dates, label):
    print(f"Label: {label}, with tickets:")
    for ticket_id, close_date in ticket_close_dates.items():
        print(f"{ticket_id}, closed: {close_date}")


# Fetch all issues with specific label
def fetch_issues_by_label(jira, label):
    issues = []
    start_index = 0
    max_results = 100

    query = (
        "project = GAN  AND status in (Closed) "
        'and labels="{label}" '
        'and resolution NOT IN ("Duplicate", "Won\'t Do", "Declined") '
        "and resolutiondate > '2022-01-01' "
        "order by resolved desc"
    )
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


def print_time_records(label, time_records):
    print(f'Label: {label} {time_records["total_tickets"]} tickets completed')
    print(f"\tTotal In Progress   (m): {time_records['total_in_progress_s']/60:7.2f}")
    print(f"\tTotal In Review     (m): {time_records['total_in_review_s']/60:7.2f}")
    print(f"\tAverage In Progress (m): {time_records['average_in_progress_s']/60:7.2f}")
    print(f"\tAverage In Review   (m): {time_records['average_in_review_s']/60:7.2f}")
    print()


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
# # https://ganaz.atlassian.net/browse/GAN-5750
def main():
    xops_labels = [
        # "xops_packet_update",
        # "xops_new_packet",
        # "xops_ch_sms_whatsapp",
        # "xops_ch_change_name", v
        # "xops_ch_message_troubleshoot",
        "xops_enable_remittances",
        # "xops_remove_profile",
        # "xops_ch_portal",
        # "xops_company_employee_id_counter",
        # "xops_reports",
    ]

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
        print(f'Fetching issues with label "{label}"...')
        # issues = load_jira_data_from_file(f"{label}_data_small.json", jira)

        issues = fetch_issues_by_label(jira, label)
        # save_jira_data_to_file(issues, f"{label}_data_small.json")

        print(f'Processing {len(issues)} issues with label "{label}"...')
        ticket_data = process_issues(jira, issues, custom_fields_map)

        # Assuming you have `ticket_data` object
        pretty_ticket_data = json.dumps(
            ticket_data, indent=4, default=datetime_serializer
        )
        print(pretty_ticket_data)

        for key, ticket in ticket_data.items():
            in_progress_duration = ticket["in_progress_s"]
            in_progress_hms = seconds_to_hms(in_progress_duration)
            in_progress_str = f"{in_progress_hms[0]} hours, {in_progress_hms[1]} minutes, {in_progress_hms[2]} seconds"
            print(
                f'ticket {key}, closing_date: {ticket["resolutiondate"]}, in_progress: {in_progress_duration}s [{in_progress_str}]'
            )
        update_aggregated_results(xops_time_records, ticket_data, label)

        print(f"total tickets: {len(ticket_data)}")

    # # Now you can calculate averages, total costs, and other required aggregations using final_results.
    # # Display aggregated results for each xops_label
    for label in xops_labels:
        print_time_records(label, xops_time_records[label])


if __name__ == "__main__":
    main()
