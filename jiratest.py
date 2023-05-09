import os
from jira import JIRA
import json
from datetime import datetime, timedelta
import numpy as np
import time_handling


def get_custom_fields_mapping(jira):
    custom_field_map = {}
    fields = jira.fields()

    for field in fields:
        if field['custom']:
            custom_field_map[field['id']] = field['name']

    return custom_field_map


def retrieve_fields(issue, custom_fields_map, result_dict):
    key = issue.key
    fields = issue.fields
    raw = issue.raw['fields']
    result_dict[key] = {
        "ID": key,
        "summary": fields.summary,
        "status": fields.status.name,
        "points": fields.customfield_10028,
        "sprint": fields.customfield_10020,
        "start": fields.customfield_10015,
        "type": raw.get("issuetype", {}).get("name"),
        "assignee": raw.get("assignee", {}).get("displayName"),
        "resolution": raw.get("resolution", {}).get("displayName"),
        "component": [c['name'] for c in raw.get("components", [])],
    }

    return result_dict


def collect_metrics(data):
    tickets = json.loads(data)
    completed_tickets = [t for t in tickets.values() if t["resolution"]["name"] not in ["Declined", "Duplicate"]]
    incident_tickets = [t for t in completed_tickets if t["type"] == "Incident"]
    non_incident_tickets_with_points = [t for t in completed_tickets if t["points"] is not None]
    non_incident_tickets_without_points = [t for t in completed_tickets if t["points"] is None]

    num_completed_tickets = len(completed_tickets)
    average_tickets_per_week = num_completed_tickets / 7
    average_points_per_week = len(non_incident_tickets_with_points) / 7

    time_spent_in_progress = sum(t["duration_total_hours_till_dev_done"] for t in completed_tickets if t["duration_total_hours_till_dev_done"] is not None)
    avg_time_spent_in_progress = time_spent_in_progress / num_completed_tickets

    print_statistics(len(incident_tickets), num_completed_tickets, len(non_incident_tickets_with_points), len(non_incident_tickets_without_points), average_tickets_per_week, average_points_per_week, avg_time_spent_in_progress)


def print_statistics(num_incidents, num_completed_tickets, num_tickets_with_points, num_tickets_without_points, avg_tickets_per_week, avg_points_per_week, avg_time_spent_in_progress):
    print(f"Total tickets rejected: {num_incidents}")
    print(f"Total tickets completed: {num_completed_tickets}")
    print(f"\t\t additional number of incidents: {num_incidents}")
    print(f"Tickets with points: {num_tickets_with_points}")
    print(f"Tickets without points: {num_tickets_without_points}")
    print(f"Average tickets completed per week: {avg_tickets_per_week}")
    print(f"Average points completed per week: {avg_points_per_week}")
    print(f"Average time (hours) spent in review: {avg_time_spent_in_progress}")


def convert_numpy_types(obj):
    if isinstance(obj, (np.int64, np.int32, np.int16)):
        return int(obj)
    elif isinstance(obj, (np.float64, np.float32)):
        return float(obj)
    else:
        return obj


jira = JIRA(options={"server": os.environ.get("JIRA_LINK")}, basic_auth=(os.environ.get("USER_EMAIL"), os.environ.get("JIRA_API_KEY")))
custom_fields_map = get_custom_fields_mapping(jira)
from_date = (datetime.now() - timedelta(days=21)).strftime('%Y-%m-%d')
jql = f"project = GAN AND (component is EMPTY OR component not in (SDET, devops)) AND issuetype in (Bug, Incident, Spike, Story, Task) AND resolutiondate >= '{from_date}'"
issues = jira.search_issues(jql)

result_dict = {}
for issue in issues:
    result = retrieve_fields(issue, custom_fields_map, result_dict)
    time_handling.update_dev_timing(jira, issue, result_dict)
    print(result)
    print("-" * 80)

result_json = json.dumps(result_dict, indent=4, default=convert_numpy_types)
print(result_json)

collect_metrics(result_json)
