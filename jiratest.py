import os
from jira import JIRA
import json
from datetime import datetime
from datetime import datetime, timedelta
import numpy as np
import time_handling


# Function to fetch custom fields and map them by ID
def get_custom_fields_mapping(jira):
    custom_field_map = {}
    fields = jira.fields()
    for field in fields:
        if field["custom"]:
            custom_field_map[field["id"]] = field["name"]

    return custom_field_map


def retrieve_fields(issue, custom_fields_map, result_dict):
    result_dict[issue.key] = {}
    result_dict[issue.key]["ID"] = issue.key
    result_dict[issue.key]["summary"] = issue.fields.summary
    result_dict[issue.key]["status"] = issue.fields.status.name
    result_dict[issue.key]["points"] = issue.fields.customfield_10028
    result_dict[issue.key]["sprint"] = issue.fields.customfield_10020
    result_dict[issue.key]["start"] = issue.fields.customfield_10015

    for field_id, field_value in issue.raw["fields"].items():
        field_name = custom_fields_map.get(
            field_id, field_id
        )  # Get field name or use ID as fallback

        if field_value is None:
            value_str = "None"
        elif isinstance(field_value, (str, int, float)):
            value_str = str(field_value)

        # Add support for issuetype display
        elif field_name == "issuetype":
            result_dict[issue.key]["type"] = field_value.get(
                "name", f"<class '{field_value.__class__.__name__}'>"
            )
            continue

        # Add support for assignee display -->  assignee (assignee): <class 'dict'>
        elif field_name == "assignee":
            result_dict[issue.key]["assignee"] = field_value.get(
                "displayName", f"<class '{field_value.__class__.__name__}'>"
            )
            continue

        elif field_name == "resolution":
            if isinstance(field_value, dict):
                result_dict[issue.key]["resolution"] = field_value
            else:
                result_dict[issue.key]["resolution"] = field_value.get(
                    "displayName", str(field_value)
                )

        elif isinstance(field_value, dict) and "value" in field_value:
            value_str = str(field_value["value"])

        else:
            value_str = f"<class '{field_value.__class__.__name__}'>"

        if field_name == "components":
            result_dict[issue.key]["component"] = []
            # print(f" print component field_name and field_id:   {field_name} ({field_id}):")
            for component in field_value:
                component_name = component["name"]
                print(f"    {component_name}")
                result_dict[issue.key]["component"].append(component_name)
        # else:
        # print(f"  {field_name} ({field_id}): {value_str}")

    return result_dict


def collect_metrics(data):
    tickets = json.loads(data)

    total_tickets_completed = 0
    total_tickets_rejected = 0
    non_incidents_with_points = 0
    non_incidents_without_points = 0
    number_of_incidents = 0
    time_spent_in_progress = 0

    # Variables to calculate average time spent in review
    total_time_spent_in_review = 0
    in_review_ticket_count = 0

    # Iterate through all tickets
    for ticket_id, ticket_info in tickets.items():
        resolution_name = ticket_info["resolution"]["name"]

        if resolution_name in ["Declined", "Duplicate"]:
            total_tickets_rejected += 1
            continue

        total_tickets_completed += 1

        if ticket_info["type"] == "Incident":
            number_of_incidents += 1

        elif ticket_info["points"] is not None:
            non_incidents_with_points += 1
        else:
            non_incidents_without_points += 1

        # Calculate time spent in progress
        if ticket_info["duration_total_hours_till_dev_done"] is not None:
            time_spent_in_progress += ticket_info["duration_total_hours_till_dev_done"]

        # Calculate average time spent in review
        if ticket_info["duration_total_hours_till_dev_done"] is not None:
            total_time_spent_in_review += ticket_info[
                "duration_total_hours_till_dev_done"
            ]
            in_review_ticket_count += 1

    # Calculate averages
    average_tickets_completed_per_week = total_tickets_completed / 7
    average_points_completed_per_week = non_incidents_with_points / 7
    average_time_spent_in_review = total_time_spent_in_review / in_review_ticket_count

    # Print out the extracted statistics
    print("Total tickets rejected:", total_tickets_rejected)
    print("Total tickets completed:", total_tickets_completed)
    print("\t\t additional number of incidents:", number_of_incidents)
    print("Tickets with points:", non_incidents_with_points)
    print("Tickets without points:", non_incidents_without_points)
    print("Average tickets completed per week:", average_tickets_completed_per_week)
    print("Average points completed per week:", average_points_completed_per_week)
    print("Average time (hours) spent in review:", average_time_spent_in_review)
    print(
        "Time / per ticket (hours):", time_spent_in_progress / total_tickets_completed
    )


def convert_numpy_types(obj):
    if isinstance(obj, (np.int64, np.int32, np.int16)):
        return int(obj)
    elif isinstance(obj, (np.float64, np.float32)):
        return float(obj)
    else:
        return obj


user = os.environ.get("USER_EMAIL")
api_key = os.environ.get("JIRA_API_KEY")
link = os.environ.get("JIRA_LINK")
options = {
    "server": link,
}

# Authenticate with JIRA API
jira = JIRA(options=options, basic_auth=(user, api_key))
custom_fields_map = get_custom_fields_mapping(jira)

# jql = "project in (GANAZ) ORDER BY Rank DESC"  # A valid JQL query
# from_date = "2023-04-14"
# we measure data since three weeks ago
three_weeks_ago = datetime.now() - timedelta(days=21)
from_date = three_weeks_ago.strftime("%Y-%m-%d")

jql = f"project = GAN AND (component is EMPTY OR component not in (SDET, devops)) AND issuetype in (Bug, Incident, Spike, Story, Task) AND resolutiondate >= '{from_date}'"

# Fetch 1 issue to confirm the API is working correctly
issues = jira.search_issues(jql)  # , maxResults=10)


result_dict = {}
if issues:
    for issue in issues:
        result = retrieve_fields(issue, custom_fields_map, result_dict)
        time_handling.update_dev_timing(jira, issue, result_dict)
        print(result)
        print("-" * 80)  # Print separator line between each issue
else:
    print("No issues found.")

print(json.dumps(result_dict, indent=4, default=convert_numpy_types))
result_json = json.dumps(result_dict, indent=4, default=convert_numpy_types)

data = json.dumps(result_dict, indent=4, default=convert_numpy_types)
collect_metrics(data)
