import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
import pytz
import numpy as np
from jira import JIRA
from jira.resources import Issue

from jira_io_utils import (
    export_metrics_csv,
    export_group_metrics_csv,
    save_jira_data_to_file,
    load_jira_data_from_file,
    fetch_issues_from_api,
    retrieve_jira_issues,
    print_records,
    print_group_records,
    print_detailed_ticket_data,
)

from jira_time_utils import (
    datetime_serializer,
    get_resolution_date,
    DateTimeEncoder,
    parse_date,
    seconds_to_hms,
    business_time_spent_in_seconds,
    get_week_intervals,
)

from jira_content_utility import (
    g_status_list,
    parse_status_changes,
    calculate_status_intervals,
    find_status_timestamps,
    save_status_timing_results,
    extract_status_durations,
    get_custom_fields_mapping,
    extract_ticket_data,
    process_issues,
    extract_closed_date,
    update_aggregated_results,
    calculate_individual_metrics,
    calculate_group_metrics,
)


def parse_arguments():
    parser = argparse.ArgumentParser(description="Query with custom timeframe.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Display detailed ticket data")
    parser.add_argument(
        "-l",
        "--load",
        action="store_true",
        help="Load from previously stored json dump of JIRA data",
    )
    parser.add_argument(
        "-s",
        "--save",
        action="store_true",
        help="Save a json dump from the JIRA data you will now retrieve, you can later use the -l --load function and avoid JIRA query overhead",
    )

    parser.add_argument(
        "--resolution-date",
        type=str,
        metavar="YYYY-MM-DD",
        help="Enter a specific resolution date in YYYY-MM-DD format",
    )

    parser.add_argument(
        "--weeks-back",
        type=int,
        help="Enter how many weeks back from today to set the resolution date",
    )

    # Parse the arguments
    args = parser.parse_args()

    # Get the resolution date parameter
    if args.resolution_date:
        resolution_date = args.resolution_date
    elif args.weeks_back:
        resolution_date = get_resolution_date(args.weeks_back)
    else:
        parser.print_help()
        exit(1)

    return args, resolution_date


def main():
    args, resolution_date = parse_arguments()

    engineering_users = [
        "Luke Dean",
        "Liz Schwab",
        "Luis Chávez",
        "Ragan Webber",
    ]

    default_metrics = {
        "total_tickets": 0,
        "total_in_progress": 0,
        "total_in_review": 0,
        "average_in_progress": 0,
        "average_in_review": 0,
        "total_ticket_points": 0,
        "average_ticket_points_weekly": 0,
    }

    # Generate data list from engineering_users and default_metrics
    data = {person: dict(default_metrics) for person in engineering_users}

    # Perform JQL query and handle pagination if needed
    user = os.environ.get("USER_EMAIL")
    api_key = os.environ.get("JIRA_API_KEY")
    link = os.environ.get("JIRA_LINK")
    options = {
        "server": link,
    }
    jira = JIRA(options=options, basic_auth=(user, api_key))
    custom_fields_map = get_custom_fields_mapping(jira)

    # Calculate minimal_date and maximal_date based on weeks_back
    timezone_str = "US/Mountain"
    timezone_choice = pytz.timezone(timezone_str)
    today = date.today().isoformat()  # today's date
    minimal_date = resolution_date  # weeks_back weeks before from today
    maximal_date = today  # today's date
    interval = 3  # set this to the number of weeks you want each time period to be

    time_records = {}
    data = {}
    intervals = get_week_intervals(minimal_date, maximal_date, interval)
    record_data = []
    overwrite_flag = {person: True for person in engineering_users}

    for i in range(len(intervals) - 1):
        #group_measurements = group_interval_metrics.copy() # copy, not referene the dictionary

        start_date = datetime.strptime(intervals[i], "%Y-%m-%d").date()
        end_date = datetime.strptime(intervals[i + 1], "%Y-%m-%d").date()
        # Convert start_date and end_date to datetime objects and set them to PDT
        start_date = timezone_choice.localize(datetime.combine(start_date, datetime.min.time()))
        end_date = timezone_choice.localize(datetime.combine(end_date, datetime.max.time()))
        # then sigh, fix it again to be in format that JIRA api likes
        start_date_str = start_date.strftime("%Y-%m-%d %H:%M")
        end_date_str = end_date.strftime("%Y-%m-%d %H:%M")

        for person in engineering_users:
            query = (
                f"project = GAN  AND status in (Closed) "
                f'and assignee="{person}" '
                f'and resolution NOT IN ("Duplicate", "Won\'t Do", "Declined", "Obsolete") '
                f'and issuetype not in ("Incident", "Epic", "Support Request") '
                f"and resolutiondate > '{start_date_str}' "
                f"and resolutiondate <= '{end_date_str}' "
                f"order by resolved desc"
            )
            # Call the new calculate_individual_metrics from here
            overwrite_flag, time_records, average_points_per_time_period, avg_in_progress, avg_in_review = calculate_individual_metrics(person, overwrite_flag, args, jira, query, start_date, end_date, custom_fields_map, time_records, interval)
            total_tickets = time_records[person]["total_tickets"]
            record_data.append(
                {
                    "Person": person,
                    f"{start_date} - {end_date}": total_tickets,
                    "Total tickets": total_tickets,
                    "Total points": time_records[person]["total_ticket_points"],
                    "Average points per Time Period": time_records[person]["average_points_per_time_period"],
                    "Average in-progress [day]": avg_in_progress,
                    "Average in-review [day]": avg_in_review,
                }
            )

            data[person] = time_records[person]
            print(f"total tickets: {total_tickets}")


    # Initialize an empty dictionary for storing the aggregated data
    group_metrics  = calculate_group_metrics(record_data)

    # Convert data dictionary into list of dicts
    data_list = [{**{"person": person}, **values} for person, values in data.items()]
    # Sort and print the records
    sorted_data = sorted(data_list, key=lambda x: x["total_tickets"], reverse=True)

    for item in sorted_data:
        print_records(item["person"], item)

    # Convert data dictionary into list of tuples for export functions
    # [("person1", 10), ("person2", 15), ...]
    data_list_1 = [(person, values["total_tickets"]) for person, values in data.items()]
    data_list_1.sort(key=lambda x: x[1], reverse=True)

    # [("person1", 3600), ("person2", 1800), ...]
    data_list_2 = [(person, values["total_in_progress"]) for person, values in data.items()]
    data_list_2.sort(key=lambda x: x[1], reverse=True)
    resolution_date_formatted = f"{resolution_date}"

    # Now use the updated data list to create CSV
    export_metrics_csv(record_data, "engineering_data/tickets_per_person.csv", "Total tickets")
    export_metrics_csv(record_data, "engineering_data/points_per_person.csv", "Total points")
    export_metrics_csv(
        record_data,
        "engineering_data/average_points_per_person.csv",
        "Average points per Time Period",
    )
    export_metrics_csv(
        record_data,
        "engineering_data/average_in_progress_time_per_person.csv",
        "Average in-progress [day]",
    )
    export_metrics_csv(
        record_data,
        "engineering_data/average_in_review_time_per_person.csv",
        "Average in-review [day]",
    )

    export_group_metrics_csv(group_metrics, "engineering_data/total_tickets.csv", "Total tickets")
    export_group_metrics_csv(group_metrics, "engineering_data/total_points.csv", "Total points")


if __name__ == "__main__":
    main()
