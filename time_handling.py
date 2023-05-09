from datetime import datetime
from jira import JIRA
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


def update_dev_timing(jira, jira_issue, result_dict):
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

