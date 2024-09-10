import os
from jira import JIRA
from jira.resources import Issue
from collections import defaultdict
from datetime import datetime, timedelta
import statistics 
import pytz

# Jira API endpoint
username = os.environ.get('USER_EMAIL')
api_key = os.environ.get('JIRA_API_KEY')
jira_url = os.environ.get('JIRA_LINK')
projects = os.environ.get('JIRA_PROJECTS').split(',')
required_env_vars = ["JIRA_API_KEY", "USER_EMAIL", "JIRA_LINK", "JIRA_PROJECTS"]
for var in required_env_vars:    
    if os.environ.get(var) is None:
        raise ValueError(f"Environment variable {var} is not set.")


hours_to_days = 8
seconds_to_hours = 3600

def get_jira_instance():
    """
    Create the jira instance
    An easy way to set up your environment variables is through your .zshrc or .bashrc file 
    export USER_EMAIL="your_email@example.com"
    export JIRA_API_KEY="your_jira_api_key"
    export JIRA_LINK="https://your_jira_instance.atlassian.net"
    """
    user = os.environ.get("USER_EMAIL")
    api_key = os.environ.get("JIRA_API_KEY")
    link = os.environ.get("JIRA_LINK")
    options = {
        "server": link,
    }
    jira = JIRA(options=options, basic_auth=(user, api_key))
    return jira

def get_tickets_from_jira(start_date, end_date):
    # Get the Jira instance
    jira = get_jira_instance()
    #jql_query = f"project in ({', '.join(projects)}) AND status in (Released) and (updatedDate >= {start_date} and updatedDate <= {end_date}) AND issueType in (Task, Bug, Story, Spike) ORDER BY updated ASC"
    jql_query = f"key in ('INT-161', 'INT-1917', 'INT-1922') AND status in (Released) and (updatedDate >= {start_date} and updatedDate <= {end_date}) AND issueType in (Task, Bug, Story, Spike) ORDER BY updated ASC"

    max_results = 100
    start_at = 0
    total_tickets = []

    while True:
        tickets = jira.search_issues(jql_query, startAt=start_at, maxResults=max_results, expand='changelog')
        if len(tickets) == 0:
            break
       
        total_tickets.extend(tickets)
        start_at += max_results
        if len(tickets) < max_results:
            break
        start_at += max_results
    return total_tickets

def validate_issue(issue):
    if not isinstance(issue, Issue):
        print(f"Unexpected type: {type(issue)}  -- ignoring")
        return False
    return True

def localize_start_date(start_date_str):
    pst = pytz.timezone('America/Los_Angeles')
    return pst.localize(datetime.strptime(start_date_str, "%Y-%m-%d"))

def log_process_process_changelog(changelog):
    # Create the complete log string first
    log_string = ""
    count = 0
    for history in reversed(changelog.histories):
        for item in history.items:
            if item.field == "status":
                status = item.toString
                count = count +1 
                log_string += f"{count} -- {history.author}, {history.created}, {item.fromString} ---> {status}\n"
    return log_string 


def process_changelog(changelog, start_date):
    code_review_statuses = {"code review", "in code review", "to review", "to code review", "in review", "in design review"}
    code_review_timestamp = None
    released_timestamp = None


    # we look at in chronological order and the FIRST time we go into code-review
    for history in reversed(changelog.histories):
        for item in history.items:
            if item.field == "status":
                status = item.toString
                if status.lower() in code_review_statuses:
                    code_review_timestamp = datetime.strptime(history.created, "%Y-%m-%dT%H:%M:%S.%f%z")
                    break
    # look at the histories in reverse-chronological order to find the LAST time it was released. 
    for history in changelog.histories:
        for item in history.items:
            if item.field == "status":
                status = item.toString
                if status.lower() == "released":
                    released_timestamp = datetime.strptime(history.created, "%Y-%m-%dT%H:%M:%S.%f%z")
                    if start_date > released_timestamp:
                        return None, None
                    break
    return code_review_timestamp, released_timestamp

def calculate_business_time(code_review_timestamp, released_timestamp):
    business_seconds = business_time_spent_in_seconds(code_review_timestamp, released_timestamp)
    business_days = business_seconds / (seconds_to_hours * hours_to_days)
    return business_seconds, business_days

def log_cycle_time(issue_key, log_string, business_seconds, business_days, code_review_timestamp, released_timestamp):
    log_string += f"Cycle time in business hours: {business_seconds / seconds_to_hours:.2f} --> days: {business_seconds / (3600 * 8):.2f}\n"
    log_string += f"Review started at: {code_review_timestamp}, released at: {released_timestamp}, Cycle time: {business_days} days\n"
    log_string += f"Cycle time in hours: {business_seconds / 3600:.2f} --> days: {business_seconds / (3600 * 8):.2f}\n"
    return log_string

def calculate_cycle_time_seconds(start_date_str, issue):
    if not validate_issue(issue):
        return None, None

    start_date = localize_start_date(start_date_str)
    code_review_timestamp, released_timestamp = process_changelog(issue.changelog, start_date)
    log_string = log_process_process_changelog(issue.changelog)

    if released_timestamp and code_review_timestamp:
        business_seconds, business_days = calculate_business_time(code_review_timestamp, released_timestamp)
        log_string = log_cycle_time(issue.key, log_string, business_seconds, business_days, code_review_timestamp, released_timestamp)
        month_key = released_timestamp.strftime("%Y-%m")
        print(f"Processing {issue.key}\n{log_string}")
        return business_seconds, month_key
    return None, None

def calculate_monthly_cycle_time(start_date, end_date):
    tickets = get_tickets_from_jira(start_date, end_date)
    cycle_times_per_month = defaultdict(list)

    
    for index, issue in enumerate(tickets):
        cycle_time, month_key = calculate_cycle_time_seconds(start_date, issue)
        if cycle_time:
            cycle_times_per_month[month_key].append(cycle_time)

    #calculate_cycle_time(cycle_times_per_month)
#     calculate_average_cycle_time_per_month(cycle_times_per_month)
#     calculate_median_cycle_time_per_month(cycle_times_per_month)
#     calculate_total_average_cycle_time(cycle_times_per_month)
#     calculate_total_median_cycle_time(cycle_times_per_month)


# def calculate_average_cycle_time_per_month(cycle_times_per_month):
#     for month, cycle_times in cycle_times_per_month.items():
#         # ignore if month is not within the current year 
#         if not month.startswith(str(datetime.now().year)):
#             continue 

#         print(f"Month: {month}")
#         if cycle_times:
#             average_cycle_time = sum(cycle_times) / len(cycle_times)
#             average_cycle_time_days = average_cycle_time / (60 * 60 * 24)  # Convert seconds to days
#             print(f"Average Cycle Time: {average_cycle_time_days:.2f}")
#         else:
#             print("No completed tickets found.")
#             print("---")

# def calculate_total_average_cycle_time(cycle_times_per_month):
#     all_cycle_times = []
#     for cycle_times in cycle_times_per_month.values():
#         all_cycle_times.extend(cycle_times)

#     if all_cycle_times:
#         total_average_cycle_time = sum(all_cycle_times) / len(all_cycle_times)
#         total_average_cycle_time_days = total_average_cycle_time / (60 * 60 * 24)  # Convert seconds to days
#         print(f"Total Average Cycle Time: {total_average_cycle_time_days:.2f} days")
#     else:
#         print("No completed tickets found to calculate average cycle time.")


# def calculate_median_cycle_time_per_month(cycle_times_per_month):
#     for month, cycle_times in cycle_times_per_month.items():
#         # ignore if month is not within the current year 
#         if not month.startswith(str(datetime.now().year)):
#             continue 

#         if cycle_times:
#             median_cycle_time = statistics.median(cycle_times)
#             median_cycle_time_days = median_cycle_time / (60 * 60 * 24)  # Convert seconds to days
            
#             print(f"Month: {month}")
#             print(f"Median Cycle Time: {median_cycle_time_days:.2f} days")
#         else:
#             print(f"Month: {month}")
#             print("No completed tickets found.")
#             print("---")
            
# def calculate_total_median_cycle_time(cycle_times_per_month):
#     all_cycle_times = []
#     for cycle_times in cycle_times_per_month.values():
#         all_cycle_times.extend(cycle_times)

#     if all_cycle_times:
#         median_cycle_time = statistics.median(all_cycle_times)
#         median_cycle_time_days = median_cycle_time / (60 * 60 * 24)  # Convert seconds to days
#         print(f"Total Median Cycle Time: {median_cycle_time_days:.2f} days")
#     else:
#         print("No completed tickets found to calculate median cycle time.")

def business_time_spent_in_seconds(start, end):
    """extract only the time spent during business hours from a jira time range -- only count 8h"""
    weekdays = [0, 1, 2, 3, 4]  # Monday to Friday
    total_business_seconds = 0
    seconds_in_workday = 8 * 60 * 60  # 8 hours * 60 minutes * 60 seconds

    current = start
    while current <= end:
        if current.weekday() in weekdays:
            day_end = current.replace(hour=23, minute=59)
            remaining_time_today = day_end - current

            if current.date() != end.date():
                total_business_seconds += min(remaining_time_today.total_seconds(), seconds_in_workday)
                current += timedelta(days=1)
                current = current.replace(hour=0, minute=0)
            else:
                remaining_time_on_last_day = end - current
                total_business_seconds += min(remaining_time_on_last_day.total_seconds(), seconds_in_workday)
                break
        else:
            current += timedelta(days=1)
            current = current.replace(hour=0, minute=0)

    return total_business_seconds

def main():
    current_year = datetime.now().year
    start_date = f"{current_year}-01-01"
    end_date = f"{current_year}-12-30"
    calculate_monthly_cycle_time(start_date, end_date)

if __name__ == "__main__":
    main()