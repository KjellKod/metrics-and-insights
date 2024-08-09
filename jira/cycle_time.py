import os
from jira import JIRA
from jira.resources import Issue
from collections import defaultdict
from datetime import datetime, timedelta
import statistics 

# Jira API endpoint
username = os.environ.get('USER_EMAIL')
api_key = os.environ.get('JIRA_API_KEY')
jira_url = os.environ.get('JIRA_LINK')

required_env_vars = ["JIRA_API_KEY", "USER_EMAIL", "JIRA_LINK"]



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
    jql_query = f"project in (ONF, ENG, MOB, 'INT') AND status in (Released) and (updatedDate >= {start_date} and updatedDate <= {end_date}) AND issueType in (Task, Bug, Story, Spike) ORDER BY updated ASC"
    
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

    print(f"Total tickets found: {len(total_tickets)}")
    return total_tickets

def calculate_cycle_time(issue):
    print("----")
    if not isinstance(issue, Issue):
        print(f"Unexpected type: {type(issue)} -- ignoringß")
        return None, None 

    # print("Attributes and methods of issue:", dir(issue))
    print(f" processing: {issue.key}")
    changelog = issue.changelog
    in_progress_time = None
    to_code_review_time = None
    released_time = None

    log_string = f"----\n{issue.key}: "
    for history in changelog.histories:
        for item in history.items:
            if item.field == "status":
                log_string += f"{history.author}, {history.created}, {item.fromString} ---> {item.toString}\n" 
                if item.toString.lower() == "in progress":
                    in_progress_time = datetime.strptime(history.created, "%Y-%m-%dT%H:%M:%S.%f%z")
                elif item.toString.lower() == "to code review" or item.toString.lower() == "to review":
                   
                    to_code_review_time = datetime.strptime(history.created, "%Y-%m-%dT%H:%M:%S.%f%z")
                elif item.toString.lower() == "released":
                    released_time = datetime.strptime(history.created, "%Y-%m-%dT%H:%M:%S.%f%z")
                    break
                elif item.toString.lower() == "ready for development" or item.toString.lower() == "draft":
                    break

    if released_time and to_code_review_time:
        business_days = business_days_between(to_code_review_time, released_time)
        month_key = released_time.strftime("%Y-%m")
        print(log_string)
        print(f"To Code Review Time: {to_code_review_time}")
        print(f"Released Time: {released_time}")
        days, hours = get_days_and_hours(business_days)
        print(f"{month_key} : Cycle Time: {days} days, {hours} hours [{issue.key}]" )
        return business_days.total_seconds(), month_key
    return None, None


def calculate_average_cycle_time_per_month(cycle_times_per_month):
    for month, cycle_times in cycle_times_per_month.items():
        # ignore if month is not within the current year 
        if not month.startswith(str(datetime.now().year)):
            continue 

        if cycle_times:
            average_cycle_time = sum(cycle_times) / len(cycle_times)
            average_cycle_time_days = average_cycle_time / (60 * 60 * 24)  # Convert seconds to days

            print(f"Month: {month}")
        
            print(f"Average Cycle Time: {average_cycle_time_days:.2f}")
            print("---")
        else:
            print(f"Month: {month}")
            print("No completed tickets found.")
            print("---")

def calculate_monthly_cycle_time(start_date, end_date):
    tickets = get_tickets_from_jira(start_date, end_date)
    cycle_times_per_month = defaultdict(list)

    
    for index, issue in enumerate(tickets):
        print(f"Processing ticket {index + 1}/{len(tickets)}")
        cycle_time, month_key = calculate_cycle_time(issue)
        if cycle_time:
            cycle_times_per_month[month_key].append(cycle_time)

    calculate_cycle_time(cycle_times_per_month)
    calculate_average_cycle_time_per_month(cycle_times_per_month)
    calculate_median_cycle_time_per_month(cycle_times_per_month)


def calculate_median_cycle_time_per_month(cycle_times_per_month):
    for month, cycle_times in cycle_times_per_month.items():
        # ignore if month is not within the current year 
        if not month.startswith(str(datetime.now().year)):
            continue 

        if cycle_times:
            median_cycle_time = statistics.median(cycle_times)
            median_cycle_time_days = median_cycle_time / (60 * 60 * 24)  # Convert seconds to days
            
            print(f"Month: {month}")
            print(f"Median Cycle Time: {median_cycle_time_days:.2f} days")
            print("---")
        else:
            print(f"Month: {month}")
            print("No completed tickets found.")
            print("---")

def get_days_and_hours(business_day: timedelta):
    total_days = business_day.days
    total_seconds = business_day.seconds
    extra_hours = total_seconds // 3600  # Convert remaining seconds to hours
    return total_days, extra_hours

def business_days_between(start_date, end_date):
    weekdays = [0, 1, 2, 3, 4]  # Monday to Friday
    business_days = 0

    current_date = start_date
    while current_date <= end_date:
        if current_date.weekday() in weekdays:
            business_days += 1
        current_date += timedelta(days=1)

    return timedelta(days=business_days)

def main():
    current_year = datetime.now().year
    start_date = f"{current_year}-01-01"
    end_date = f"{current_year}-12-30"
    calculate_monthly_cycle_time(start_date, end_date)

if __name__ == "__main__":
    main()