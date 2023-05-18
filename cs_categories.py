import os
from jira import JIRA
import json
from datetime import datetime, timedelta
import numpy as np

# import time_handling
# -------
from datetime import datetime
from jira import JIRA
import numpy as np

# Function to parse dates


def datetime_serializer(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")


def parse_date(date_str):
    if date_str is not None:
        return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S.%f%z")
    return None


# Function to calculate business days between two dates


def business_days_between(start_date, end_date):
    business_days = np.busday_count(start_date.date(), end_date.date())
    return business_days


# Function to calculate business days between two dates, including partial days & remaining hours


def business_days_and_hours_between(start_date, end_date):
    WORK_HOURS_PER_DAY = 8
    business_days = np.busday_count(start_date.date(), end_date.date())
    remaining_hours_on_first_day = (
        min(WORK_HOURS_PER_DAY - start_date.hour, end_date.hour)
        if start_date.date() == end_date.date()
        else WORK_HOURS_PER_DAY - start_date.hour
    )
    remaining_hours_on_last_day = (
        end_date.hour if start_date.date() != end_date.date() else 0
    )
    total_business_hours = (
        business_days * WORK_HOURS_PER_DAY
        + remaining_hours_on_first_day
        + remaining_hours_on_last_day
    )

    return business_days, total_business_hours


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


def calculate_in_progress_intervals(status_changes, status_to_measure):
    in_progress_intervals = []
    in_progress_start = None

    for change in status_changes:
        if change["to"] == status_to_measure:
            in_progress_start = change["timestamp"]
        elif in_progress_start is not None and change["from"] == status_to_measure:
            in_progress_end = change["timestamp"]
            in_progress_intervals.append((in_progress_start, in_progress_end))
            in_progress_start = None

    return in_progress_intervals


def find_status_timestamps(status_changes, *statuses):
    timestamps = {status: None for status in statuses}

    for change in status_changes:
        if change["to"] in statuses:
            if not timestamps[change["to"]]:  # Add this line
                timestamps[change["to"]] = change["timestamp"]

    return timestamps


def extract_status_durations(jira, jira_issue, result_dict):
    issue = jira.issue(jira_issue.key, expand="changelog")

    status_changes = parse_status_changes(issue.changelog.histories)
    in_progress_intervals = calculate_in_progress_intervals(
        status_changes, "In Progress"
    )
    in_review_intervals = calculate_in_progress_intervals(status_changes, "In Review")

    status_timestamps = find_status_timestamps(
        status_changes,
        "TODO",
        "Prioritized",
        "In Progress",
        "In Review",
        "Pending Staging",
        "Closed",
        "Pending Release",
    )

    # Print the variables
    print(
        "Status Changes:",
        json.dumps(status_changes, indent=2, default=datetime_serializer),
    )
    print(
        "In Progress Intervals:",
        json.dumps(in_progress_intervals, indent=2, default=datetime_serializer),
    )
    print(
        "In-Review  Intervals:",
        json.dumps(in_review_intervals, indent=2, default=datetime_serializer),
    )
    print(
        "Status Timestamps:",
        json.dumps(status_timestamps, indent=2, default=datetime_serializer),
    )

    earliest_end_datetime = min(
        (ts for ts in status_timestamps.values() if ts is not None), default=None
    )

    business_days, in_progress_hours = (None, None)
    if (
        status_timestamps["In Progress"] is not None
        and earliest_end_datetime is not None
    ):
        business_days, in_progress_hours = business_days_and_hours_between(
            status_timestamps["In Progress"], earliest_end_datetime
        )

    business_days_in_review, hours_in_review = (None, None)
    if status_timestamps["In Review"] is not None and earliest_end_datetime is not None:
        business_days_in_review, hours_in_review = business_days_and_hours_between(
            status_timestamps["In Review"], earliest_end_datetime
        )

    # Calculate total time spent in "In Progress" status
    total_in_progress_seconds = sum(
        (end - start).total_seconds() for start, end in in_progress_intervals
    )
    total_in_progress_minutes = round(total_in_progress_seconds / 60)
    total_in_progress_hours_and_minutes = divmod(total_in_progress_minutes, 60)

    result_dict[issue.key]["in_progress_weekdays"] = business_days
    result_dict[issue.key]["hours_in_progress"] = in_progress_hours
    result_dict[issue.key]["in_progress_minutes"] = total_in_progress_minutes
    result_dict[issue.key][
        "in_progress_hours_and_minutes"
    ] = total_in_progress_hours_and_minutes
    result_dict[issue.key]["in_review_weekdays"] = business_days_in_review
    result_dict[issue.key]["in_review_hours"] = hours_in_review


# -------
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


def convert_numpy_types(obj):
    if isinstance(obj, (np.int64, np.int32, np.int16)):
        return int(obj)
    elif isinstance(obj, (np.float64, np.float32)):
        return float(obj)
    else:
        return obj


def calculate_averages(keyword_tickets):
    total_time_in_progress = sum(
        ticket["time_in_progress"]
        for ticket in keyword_tickets
        if ticket["time_in_progress"]
    )
    total_time_in_review = sum(
        ticket["time_in_review"]
        for ticket in keyword_tickets
        if ticket["time_in_review"]
    )

    if len(keyword_tickets) > 0:
        average_time_in_progress = total_time_in_progress / len(keyword_tickets)
    else:
        average_time_in_progress = 0

    compound_time_in_progress = total_time_in_progress

    return {
        "average_time_in_progress": average_time_in_progress,
        "compound_time_in_progress": compound_time_in_progress,
    }


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

        for key, ticket in ticket_data.items():
            ticket_id = ticket["ID"]
            title = ticket["summary"]
            in_progress_time_minutes = ticket["in_progress_minutes"]
            in_progress_time_hours_minutes = ticket["in_progress_hours_and_minutes"]
            in_review_time_hours = ticket["in_review_hours"]

            print(
                f"{ticket_id}: {title.ljust(45)} in-progress: {in_progress_time_minutes} m. {in_progress_time_hours_minutes[0]}h. {in_progress_time_hours_minutes[1]}m, in-review: {in_review_time_hours}h"
            )

    # result_dict[issue.key]["in_progress_weekdays"] = time_till_in_progress_ended_business_days
    # result_dict[issue.key]["hours_in_progress"] = total_in_progress_hours
    # result_dict[issue.key]["in_progress_minutes"] = total_in_progress_minutes
    # result_dict[issue.key]["in_progress_hours_and_minutes"] = total_in_progress_hours_and_minutes
    # result_dict[issue.key]["in_review_weekdays"] = time_to_finish_in_review_business_days
    # result_dict[issue.key]["in_review_hours"] = time_to_finish_in_review_hours\

    # average_in_progress = total_in_progress_time // len(ticket_data)
    # average_in_review = total_in_review_time // len(ticket_data)

    # print(f"total ")
    # print(f"average in-progress: {average_in_progress}h")
    # print(f"average in-review: {average_in_review}h")
    # print(f"total time used in-progress: {total_in_progress_time}h")


if __name__ == "__main__":
    main()
