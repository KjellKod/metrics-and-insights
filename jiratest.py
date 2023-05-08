import os 
from jira import JIRA
import json 
from datetime import datetime
import numpy as np


# Function to parse dates
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
    business_days = np.busday_count(start_date.date(), end_date.date())
    remaining_hours_on_first_day = min(8 - start_date.hour, end_date.hour) if start_date.date() == end_date.date() else 8 - start_date.hour
    remaining_hours_on_last_day = end_date.hour if start_date.date() != end_date.date() else 0
    total_business_hours = business_days * 8 + remaining_hours_on_first_day + remaining_hours_on_last_day

    return business_days, total_business_hours


# Function to fetch custom fields and map them by ID
def get_custom_fields_mapping(jira):
    custom_field_map = {}
    fields = jira.fields()
    for field in fields:
        if field['custom']:
            custom_field_map[field['id']] = field['name']
    return custom_field_map

def retrieve_fields(issue, custom_fields_map, result_dict):
    result_dict[issue.key] = {}
    result_dict[issue.key]["ID"] = issue.key
    result_dict[issue.key]["summary"] = issue.fields.summary
    result_dict[issue.key]["status"]= issue.fields.status.name
    result_dict[issue.key]["points"] =issue.fields.customfield_10028
    result_dict[issue.key]["sprint"] =issue.fields.customfield_10020
    result_dict[issue.key]["start"] =issue.fields.customfield_10015

    for field_id, field_value in issue.raw['fields'].items():
        field_name = custom_fields_map.get(field_id, field_id)  # Get field name or use ID as fallback

        if field_value is None:
            value_str = "None"
        elif isinstance(field_value, (str, int, float)):
            value_str = str(field_value)

        # Add support for issuetype display
        elif field_name == "issuetype":
            result_dict[issue.key]["type"] = field_value.get("name", f"<class '{field_value.__class__.__name__}'>")
            continue

        # Add support for assignee display -->  assignee (assignee): <class 'dict'>
        elif field_name == "assignee":
            result_dict[issue.key]["assignee"] = field_value.get("displayName", f"<class '{field_value.__class__.__name__}'>")
            continue 

        # # Add support for resolution display
        # elif field_name == "resolution":
        #     result_dict[issue.key]["resolution"] =  field_value.get("displayName", f"<class '{field_value.__class__.__name__}'>")
        elif field_name == "resolution":
            if isinstance(field_value, dict):
                result_dict[issue.key]["resolution"] = field_value
            else:
                result_dict[issue.key]["resolution"] = field_value.get("displayName", str(field_value))
       

        elif isinstance(field_value, dict) and 'value' in field_value:
            value_str = str(field_value['value'])

        else:
            value_str = f"<class '{field_value.__class__.__name__}'>"

        if field_name == "components":
            result_dict[issue.key]["component"] = []
            #print(f" print component field_name and field_id:   {field_name} ({field_id}):")
            for component in field_value:
                component_name = component['name']
                print(f"    {component_name}")
                result_dict[issue.key]["component"].append(component_name)
        #else:
            #print(f"  {field_name} ({field_id}): {value_str}")

    return result_dict


def convert_numpy_types(obj):
    if isinstance(obj, (np.int64, np.int32, np.int16)):
        return int(obj)
    elif isinstance(obj, (np.float64, np.float32)):
        return float(obj)
    else:
        return obj


def update_dev_timing(jira_issue, result_dict):
    issue = jira.issue(jira_issue.key, expand='changelog')
    # Initialize variables
    in_progress_start = in_review_start = pending_staging_start = closed_timestamp = pending_release_timestamp = None

    # Iterate over issue's changelog history
    for history in issue.changelog.histories:
        for item in history.items:
            if item.field == 'status':
                # Check if status changed to "In Progress"
                if item.toString == 'In Progress':
                    in_progress_start = history.created
                # Check if status changed to "In Review"
                elif item.toString == 'In Review':
                    in_review_start = history.created
                # Check if status changed to "Pending Staging"
                elif item.toString == 'Pending Staging':
                    pending_staging_start = history.created
                # Check if status changed to "Closed"
                elif item.toString == 'Closed':
                    closed_timestamp = history.created
                # Check if status changed to "pending release"
                elif item.toString == 'Pending Release':
                    pending_release_timestamp = history.created

    # Convert strings to datetimes
    in_progress_datetime = parse_date(in_progress_start)
    in_review_datetime = parse_date(in_review_start)
    pending_staging_datetime = parse_date(pending_staging_start)
    closed_datetime = parse_date(closed_timestamp)
    pending_release_datetime = parse_date(pending_release_timestamp)

    # Find the earliest datetime among the specified statuses
    earliest_datetime = None
    for dt in [pending_staging_datetime, closed_datetime, pending_release_datetime]:
        if dt is not None and (earliest_datetime is None or dt < earliest_datetime):
            earliest_datetime = dt

    # Check if both in_progress_datetime and in_review_datetime have valid values before calculating business days and hours
    if in_progress_datetime is not None and in_review_datetime is not None:
        time_till_review_business_days, time_till_review_hours = business_days_and_hours_between(in_progress_datetime, in_review_datetime)
    else:
        time_till_review_business_days, time_till_review_hours = (None, None)

    # Check if both in_progress_datetime and earliest_datetime have valid values before calculating business days and hours
    if in_progress_datetime is not None and earliest_datetime is not None:
        time_till_wrapped_up_business_days, time_till_wrapped_up_hours = business_days_and_hours_between(in_progress_datetime, earliest_datetime)
    else:
        time_till_wrapped_up_business_days, time_till_wrapped_up_hours = (None, None)

    result_dict[issue.key]["duration_weekdays_in_progress"] = time_till_review_business_days
    result_dict[issue.key]["duration_total_hours_in_progress"] = time_till_review_hours
    result_dict[issue.key]["duration_weekdays_till_dev_done"] = time_till_wrapped_up_business_days
    result_dict[issue.key]["duration_total_hours_till_dev_done"] = time_till_wrapped_up_hours





user = "kjell@ganaz.com"
api_key = os.environ.get("JIRA_API_KEY")
print(f"{api_key}")
link = "https://ganaz.atlassian.net"
options = {
    'server': link,
}

# Authenticate with JIRA API
jira = JIRA(options=options, basic_auth=(user, api_key))
custom_fields_map = get_custom_fields_mapping(jira)

#jql = "project in (GANAZ) ORDER BY Rank DESC"  # A valid JQL query
from_date = "2023-04-14"
jql = f"project = GAN AND (component is EMPTY OR component not in (SDET, devops)) AND issuetype in (Bug, Incident, Spike, Story, Task) AND resolutiondate >= '{from_date}'"

# Fetch 1 issue to confirm the API is working correctly
issues = jira.search_issues(jql, maxResults=5)


result_dict = {}
if issues:
    for issue in issues:
        result = retrieve_fields(issue, custom_fields_map, result_dict)
        update_dev_timing(issue, result_dict)
        print(result)
        print("-" * 80)  # Print separator line between each issue
else:
    print("No issues found.")

print(json.dumps(result_dict, indent=4, default=convert_numpy_types))



