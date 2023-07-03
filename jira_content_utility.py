from collections import defaultdict
from jira_time_utils import parse_date, business_time_spent_in_seconds

g_status_list = ["In Progress", "In Review", "Pending Release"]


def parse_status_changes(histories):
    status_changes = []

    # Sort histories by created timestamp in ascending order (chronologically)
    sorted_histories = sorted(histories, key=lambda history: parse_date(history.created))

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
        in_progress_sum = sum([interval["adjusted_duration_s"] for interval in ticket.get("In Progress", [])])
        in_review_sum = sum([interval["adjusted_duration_s"] for interval in ticket.get("In Review", [])])
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
            result_dict[issue.key]["type"] = field_value.get("name", f"<class '{field_value.__class__.__name__}'>")
            continue
        # Add support for assignee display -->  assignee (assignee): <class 'dict'>
        elif field_name == "assignee":
            result_dict[issue.key]["assignee"] = (
                field_value.get("displayName", f"<class '{field_value.__class__.__name__}'>") if field_value else None
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


def update_aggregated_results(time_records, ticket_data, label):
    total_adjusted_in_progress_seconds = 0
    total_adjusted_in_review_seconds = 0
    total_tickets = len(ticket_data)
    total_ticket_points = 0

    for key, ticket in ticket_data.items():
        in_progress_intervals = ticket.get("In Progress", [])
        in_review_intervals = ticket.get("In Review", [])

        for interval in in_progress_intervals:
            adjusted_duration_s = interval["adjusted_duration_s"]
            total_adjusted_in_progress_seconds += adjusted_duration_s

        for interval in in_review_intervals:
            adjusted_duration_s = interval["adjusted_duration_s"]
            total_adjusted_in_review_seconds += adjusted_duration_s

    average_in_progress_s = total_adjusted_in_progress_seconds / total_tickets if total_tickets > 0 else 0
    average_in_review_s = total_adjusted_in_review_seconds / total_tickets if total_tickets > 0 else 0

    time_records[label] = {
        "total_tickets": len(ticket_data),
        "total_in_progress": total_adjusted_in_progress_seconds,
        "total_in_review": total_adjusted_in_review_seconds,
        "average_in_progress": average_in_progress_s,
        "average_in_review": average_in_review_s,
        "total_tickets": total_tickets,
    }

    return time_records
