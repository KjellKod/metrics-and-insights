import os
import csv
import json
import pytz
from datetime import datetime
from dateutil import parser
from jira import JIRA
from jira.resources import Issue
from dateutil.parser import parse

def export_metrics_csv(data, filename, metric_field):
    # Pivot data to wide format
    pivot_data = {}
    for row in data:
        if row["Person"] not in pivot_data:
            pivot_data[row["Person"]] = {"Person": row["Person"]}

        # Get the date range key from the row dictionary
        date_range_key = [key for key in row.keys() if "-" in key][0]

        # Split date range string into start and end dates
        start_date_str, end_date_str = date_range_key.split(" - ")

        # Parse the dates, format them without time, and combine them back together
        new_date_range = "{} - {}".format(parse(start_date_str).strftime('%m-%d'), parse(end_date_str).strftime('%m-%d'))

        pivot_data[row["Person"]][new_date_range] = row[metric_field]  # Update only the necessary field

    with open(filename, mode="w", newline="") as csvfile:
        writer = csv.writer(csvfile)

        # Write a title (timeframe)
        writer.writerow([metric_field])

        # Get the headers from the keys of the first dictionary
        headers = [k for k in list(pivot_data.values())[0].keys() if k != "Person"]
        writer.writerow(["Person"] + headers)  # Person will be the first column

        # Add the data row by row
        for name, row in pivot_data.items():
            writer.writerow([name] + [row.get(h, "") for h in headers])  # Use get method with default value ''

    print(f"CSV file '{filename}' has been generated.")



def export_group_metrics_csv(data, filename, metric):
    # Open/create a file with the provided filename in write mode
    with open(filename, 'w', newline='') as csvfile:
        # Initialize a writer object with the first row as headers
        fieldnames = ['Date Range', metric]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        # Write the column headers
        writer.writeheader()
        
        # Loop through each date range in the dictionary
        for date_range, metrics in data.items():
            # Extract only the specific metric from the value dictionary
            metric_value = metrics[metric]
            
            # Split date range string into start and end dates
            start_date_str, end_date_str = date_range.split(" - ")
            
            # Parse the dates, format them without time, and combine them back together
            new_date_range = "{} - {}".format(parse(start_date_str).strftime('%m-%d'), parse(end_date_str).strftime('%m-%d'))
            
            # Write the date range and extracted metric to the CSV file
            writer.writerow({'Date Range': new_date_range, metric: metric_value})

    print(f"CSV file '{filename}' has been generated.")



def save_jira_data_to_file(data, file_name, overwrite_flag):
    if overwrite_flag:
        with open(file_name, "w") as outfile:
            json.dump([issue.raw for issue in data], outfile)
    else:
        with open(file_name, "r+") as outfile:
            try:
                file_data = json.load(outfile)
            except ValueError:
                file_data = []

            file_data.extend(issue.raw for issue in data)

            outfile.seek(0)
            json.dump(file_data, outfile)


def load_jira_data_from_file(file_name, jira_instance, start_date, end_date):
    with open(f"{file_name}", "r") as infile:
        raw_issues_data = json.load(infile)

    timezone_str = "US/Mountain"

    # Convert given start_date & end_date to datetime and make them timezone aware
    print(f"start_date -- end_date: {start_date} -- {end_date}")
    start_date = pytz.timezone(timezone_str).localize(datetime.combine(start_date, datetime.min.time()))
    end_date = pytz.timezone(timezone_str).localize(datetime.combine(end_date, datetime.max.time()))

    print(f"start_date2 -- end_date2: {start_date} -- {end_date}")

    # Filter out the issues that are not within the required date-time range
    filtered_issues_data = [
        raw_issue
        for raw_issue in raw_issues_data
        if parser.parse(raw_issue["fields"]["resolutiondate"]).astimezone(pytz.timezone(timezone_str)) > start_date
        and parser.parse(raw_issue["fields"]["resolutiondate"]).astimezone(pytz.timezone(timezone_str)) <= end_date
    ]

    issues = [Issue(jira_instance._options, jira_instance._session, raw) for raw in filtered_issues_data]
    return issues


def fetch_issues_from_api(jira, query):
    issues = []
    start_index = 0
    max_results = 100

    print(f" Executing query:\n\t [{query}]")

    while True:
        chunk = jira.search_issues(
            jql_str=query,
            startAt=start_index,
            maxResults=max_results,
            expand="changelog",
        )

        if len(chunk) == 0:
            break

        issues.extend(chunk)
        start_index += max_results

    return issues

def printIssues(issues):
    for issue in issues:
        print(f"{issue.key}\t Resolution: {issue.fields.resolution.name}: {issue.fields.resolutiondate}")

def print_records(category, records):
    print(f'Person: {category} {records["total_tickets"]} tickets completed')
    print(f"\tTotal points: {records['total_ticket_points']}")
    print(f"\tTotal Time In Progress   (m): {records['total_in_progress']/60:7.2f}")
    print(f"\tTotal Time In Review     (m): {records['total_in_review']/60:7.2f}")
    print(f"\tAverage In Progress (m): {records['average_in_progress']/60:7.2f}")
    print(f"\tAverage In Review   (m): {records['average_in_review']/60:7.2f}")
    print()

def print_group_records(group, records):
    print(f'Group: {group} {records["total_tickets"]} total tickets')
    print(f"\tTotal points: {records['total_ticket_points']}")
    print()

def print_detailed_ticket_data(ticket_data):
    # Assuming you have `ticket_data` object
    pretty_ticket_data = json.dumps(ticket_data, indent=4, default=datetime_serializer)
    print(pretty_ticket_data)

    for key, ticket in ticket_data.items():
        in_progress_duration = ticket["in_progress_s"]
        in_progress_hms = seconds_to_hms(in_progress_duration)
        in_progress_str = f"{in_progress_hms[0]} hours, {in_progress_hms[1]} minutes, {in_progress_hms[2]} seconds"
        print(
            f'ticket {key}, closing_date: {ticket["resolutiondate"]}, in_progress: {in_progress_duration}s [{in_progress_str}]'
        )

        
def retrieve_jira_issues(args, jira, query, tag, path, overwrite_flag, start_date, end_date):
    issues = {}
    jira_file = f"{path}/{tag}_data.json"
    if args.load:
        jira_file = f"{path}/{tag}_data.json"
        if not os.path.exists(jira_file):
            print(
                f"\nWARNING {jira_file} does not exist. The data is missing, or you need to retrieve JIRA data first and save it with the '-s' option first.\n"
            )
            return []  # Return an empty list or handle the error accordingly
        issues = load_jira_data_from_file(jira_file, jira, start_date, end_date)
        if issues is None:
            print("Failed to load JIRA data from file")
            return []  # Return an empty list or handle the error accordingly
        print(f"Load jira from file,  {start_date} to {end_date}: {len(issues)} tickets from {jira_file}")
    else:
        issues = fetch_issues_from_api(jira, query)
        print(f'Fetched {len(issues)} issues for  "{tag}"...')

    printIssues(issues)
    if args.save:
        print(f"Saving JIRA {len(issues)} issues to {jira_file}")
        save_jira_data_to_file(issues, jira_file, overwrite_flag)
    return issues
