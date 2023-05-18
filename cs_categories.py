import os
from jira import JIRA
import json
from datetime import datetime, date, timedelta
import numpy as np

# import time_handling
# -------
from datetime import datetime
from jira import JIRA
import numpy as np

# Function to parse dates


import numpy as np


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


def business_days_and_hours_between(start, end):
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

    result_dict[issue_key][status] = [
        {
            "start": start,
            "end": end,
            "duration": (end - start).total_seconds(),
            "adjusted_duration": business_days_and_hours_between(start, end),
        }
        for state, start, end in intervals
    ]


def extract_status_durations(jira, jira_issue, result_dict):
    issue = jira.issue(jira_issue.key, expand="changelog")

    status_changes = parse_status_changes(issue.changelog.histories)
    status_list = ["In Progress", "In Review", "Pending Release"]

    for status in status_list:
        intervals = calculate_status_intervals(status_changes, status)

        # Include state name, start, and end times when printing each interval
        formatted_intervals = [
            {
                "state": state,
                "start": start,
                "end": end,
                "duration": (end - start).total_seconds(),
            }
            for state, start, end in intervals
        ]

        # print(json.dumps(formatted_intervals, indent=2, cls=DateTimeEncoder))
        save_status_timing_results(result_dict, issue.key, status, intervals)


# Function to fetch custom fields and map them by ID
def get_custom_fields_mapping(jira):
    custom_field_map = {}
    fields = jira.fields()
    for field in fields:
        if field["custom"]:
            custom_field_map[field["id"]] = field["name"]

    return custom_field_map


def extract_ticket_data(issue, custom_fields_map, result_dict):
    result_dict[issue.key] = {}
    result_dict[issue.key]["ID"] = issue.key
    result_dict[issue.key]["summary"] = issue.fields.summary
    result_dict[issue.key]["status"] = issue.fields.status.name
    result_dict[issue.key]["points"] = issue.fields.customfield_10028
    result_dict[issue.key]["sprint"] = issue.fields.customfield_10020
    result_dict[issue.key]["start"] = issue.fields.customfield_10015

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

    return result_dict


# https://ganazhq.slack.com/archives/C03BR47GDQW/p1684342201816599
# xops_ch_sms_whatsapp
# xops_ch_change_name
# xops_ch_message_troubleshoot
# xops_enable_remittances
# xops_remove_profile
# xops_packet_update
# xops_new_packet
def main():
    # Authenticate with JIRA API
    user = os.environ.get("USER_EMAIL")
    api_key = os.environ.get("JIRA_API_KEY")
    link = os.environ.get("JIRA_LINK")
    options = {
        "server": link,
    }
    jira = JIRA(options=options, basic_auth=(user, api_key))
    custom_fields_map = get_custom_fields_mapping(jira)

    weeks_ago = datetime.now() - timedelta(days=70)
    from_date = weeks_ago.strftime("%Y-%m-%d")

    labels_list = [
        # "xops_ch_sms_whatsapp",
        # "xops_ch_change_name",
        # "xops_ch_message_troubleshoot",
        # "xops_enable_remittances",
        # "xops_remove_profile",
        "xops_packet_update",
        # "xops_new_packet"
    ]

    labels = {label: [] for label in labels_list}

    for label in labels:
        # jql = f"project = GAN AND created >= startOfYear() AND labels = {label} AND Status = Closed ORDER BY duedate ASC"
        jql = f"project = GAN AND KEY='GAN-5614' AND created >= startOfYear() AND labels = {label} ORDER BY duedate ASC"
        issues = jira.search_issues(jql)
        ticket_data = {}

        for issue in issues:
            ticket_data = extract_ticket_data(issue, custom_fields_map, ticket_data)
            extract_status_durations(jira, issue, ticket_data)

    # print(
    #     "Ticket Data:", json.dumps(ticket_data, indent=2, default=datetime_serializer)
    # )

    for key, ticket in ticket_data.items():
        ticket_id = ticket["ID"]
        title = ticket["summary"]

        # In-Progress time
        in_progress_time_seconds = sum(
            [entry["duration"] for entry in ticket.get("In Progress", [])]
        )
        in_progress_hours, in_progress_minutes, in_progress_seconds = seconds_to_hms(
            in_progress_time_seconds
        )

        # In-Review time
        in_review_time_seconds = sum(
            [entry["duration"] for entry in ticket.get("In Review", [])]
        )
        in_review_hours, in_review_minutes, in_review_seconds = seconds_to_hms(
            in_review_time_seconds
        )

        # In-pending_release time
        in_pending_releasetime_seconds = sum(
            [entry["duration"] for entry in ticket.get("Pending Release", [])]
        )
        (
            in_pending_release_hours,
            in_pending_release_minutes,
            in_pending_release_seconds,
        ) = seconds_to_hms(in_pending_releasetime_seconds)

        print(
            f"{ticket_id}: {title.ljust(45)} \n\t"
            f"in-progress: {in_progress_hours} hours, {in_progress_minutes} minutes, and {in_progress_seconds:.2f} seconds,\n\t"
            f"in-review: {in_review_hours} hours, {in_review_minutes} minutes, and {in_review_seconds:.2f} seconds,\n\t"
            f"in-pending-release: {in_pending_release_hours} hours, {in_pending_release_minutes} minutes, and {in_pending_release_seconds:.2f} seconds"
        )


if __name__ == "__main__":
    main()
