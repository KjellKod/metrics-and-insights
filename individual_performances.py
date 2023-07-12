import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import date
import pytz
import numpy as np
from jira import JIRA
from jira.resources import Issue

from jira_io_utils import (
    get_jira_instance,
    export_metrics_csv,
    export_group_metrics_csv,
    save_jira_data_to_file,
    load_jira_data_from_file,
    fetch_issues_from_api,
    retrieve_jira_issues,
    print_records,
    print_group_records,
    print_detailed_ticket_data,
    print_sorted_person_data,
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
    process_jira_content_in_intervals,
    calculate_individual_metrics,
    calculate_group_metrics,
)


def parse_arguments():
    parser = argparse.ArgumentParser(description="Query with custom timeframe.")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Display detailed ticket data"
    )
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


def export_metrics_to_csv(record_data, group_metrics):
    export_metrics_csv(
        record_data, "engineering_data/tickets_per_person.csv", "Total tickets"
    )
    export_metrics_csv(
        record_data, "engineering_data/points_per_person.csv", "Total points"
    )
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

    export_group_metrics_csv(
        group_metrics, "engineering_data/total_tickets.csv", "Total tickets"
    )
    export_group_metrics_csv(
        group_metrics, "engineering_data/total_points.csv", "Total points"
    )


def setup_variables():
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

    return engineering_users, default_metrics


def main():
    args, resolution_date = parse_arguments()
    engineering_users, default_metrics = setup_variables()

    # Perform JQL query and handle pagination if needed
    jira = get_jira_instance()
    custom_fields_map = get_custom_fields_mapping(jira)

    # Calculate minimal_date and maximal_date based on weeks_back
    timezone_choice = pytz.timezone("US/Mountain")
    minimal_date = resolution_date  # weeks_back weeks before from today
    maximal_date = date.today().isoformat()  # today's date
    interval = 3  # set this to the number of weeks you want each time period to be

    intervals = get_week_intervals(minimal_date, maximal_date, interval)
    record_data, time_records = process_jira_content_in_intervals(
        args,
        engineering_users,
        jira,
        custom_fields_map,
        timezone_choice,
        interval,
        intervals,
    )

    # Initialize an empty dictionary for storing the aggregated data
    group_metrics = calculate_group_metrics(record_data)
    print_sorted_person_data(time_records)

    # Now use the updated data list to create CSV
    export_metrics_to_csv(record_data, group_metrics)


if __name__ == "__main__":
    main()
