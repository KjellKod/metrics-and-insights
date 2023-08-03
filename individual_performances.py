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
from pathlib import Path

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


def parse_arguments(parser):
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

    parser.add_argument(
        "--metrics",
        type=str,
        choices=["xops", "engineering"],
        help='Choose between "xops" mode or "engineering" metrics mode',
    )

    # Parse the arguments
    try:
        args = parser.parse_args()

        # Get the resolution date parameter
        if args.resolution_date:
            resolution_date = args.resolution_date
        elif args.weeks_back:
            resolution_date = get_resolution_date(args.weeks_back)
        else:
            raise argparse.ArgumentTypeError("Failed to parse resolution date")

        # Check if 'xops' or 'engineering' have been provided. If not, raise an exception
        if args.metrics is None or args.metrics.lower() not in ["xops", "engineering"]:
            raise argparse.ArgumentTypeError("Must choose either 'xops' or 'engineering' for metrics mode!")

        # If both --resolution-date and --weeks-back were provided, raise an exception
        if args.resolution_date and args.weeks_back:
            raise argparse.ArgumentTypeError("Can only choose either --resolution-date or --weeks-back, not both!")

    except (argparse.ArgumentError, argparse.ArgumentTypeError) as err:
        print(str(err))
        parser.print_help()
        exit(2)

    return args, resolution_date


def export_metrics_to_csv(record_data, group_metrics, storage_location, query_mode):
    export_metrics_csv(record_data, f"{storage_location}/tickets_per_{query_mode}.csv", "Total tickets")
    export_metrics_csv(record_data, f"{storage_location}/points_per_{query_mode}.csv", "Total points")
    export_metrics_csv(
        record_data,
        f"{storage_location}/average_points_per_{query_mode}.csv",
        "Average points per Time Period",
    )
    export_metrics_csv(
        record_data,
        f"{storage_location}/average_in_progress_time_per_{query_mode}.csv",
        "Average in-progress [day]",
    )
    export_metrics_csv(
        record_data,
        f"{storage_location}/average_in_review_time_per_{query_mode}.csv",
        "Average in-review [day]",
    )

    export_group_metrics_csv(group_metrics, f"{storage_location}/total_tickets.csv", "Total tickets")
    export_group_metrics_csv(group_metrics, f"{storage_location}/total_points.csv", "Total points")


def setup_variables():
    engineering_users = [
        "Luke Dean",
        "Liz Schwab",
        "Luis Chávez",
        "Ragan Webber",
    ]

    xops_labels = [
        "xops_packet_update",
        "xops_new_packet",
        "xops_ch_sms_whatsapp",
        "xops_ch_change_name",
        "xops_ch_message_troubleshoot",
        "xops_enable_remittances",
        "xops_remove_profile",
        "xops_ch_portal",
        "xops_ch_assorted",
        "xops_assorted",
        "xops_company_employee_id_counter",
        "xops_raffle",
        "xops_reports",
        "xops_carholder_assorted",
        "xops_remove_incomplete_packets" "xops_new_packet",
        "xops_training_tracks",
        "xops_paystubs",
        "xops_transfer_funds",
        "xops_company_message",
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

    return engineering_users, xops_labels, default_metrics


def main():
    parser = argparse.ArgumentParser(
        description="Specify metrics xops/engineering and for which timeframe. You can save all the JIRA data or load previously saved data"
    )
    try:
        (
            args,
            resolution_date,
        ) = parse_arguments(parser)
    except SystemExit:
        print("\n")
        parser.print_help()
        exit(2)

    engineering_users, xops_labels, default_metrics = setup_variables()

    # Perform JQL query and handle pagination if needed
    jira = get_jira_instance()
    custom_fields_map = get_custom_fields_mapping(jira)

    # Calculate minimal_date and maximal_date based on weeks_back
    timezone_choice = pytz.timezone("US/Mountain")
    minimal_date = resolution_date  # weeks_back weeks before from today
    maximal_date = date.today().isoformat()  # today's date
    interval = 3  # set this to the number of weeks you want each time period to be

    intervals = get_week_intervals(minimal_date, maximal_date, interval)

    # According to the chosen mode, change the variables
    if args.metrics == "engineering":
        query_mode = "assignee"
        query_data = engineering_users
        storage_location = "engineering_data"

    elif args.metrics == "xops":
        query_mode = "labels"
        query_data = xops_labels
        storage_location = "xops_data"

    # Create target Directory if don't exist
    directory = Path(storage_location)
    if not directory.exists():
        directory.mkdir(parents=True, exist_ok=True)
        print("Directory ", directory, " created ")

    record_data, time_records = process_jira_content_in_intervals(
        args,
        query_mode,  # "assignee",  # labels
        query_data,  # engineering_users, xops_labels
        jira,
        custom_fields_map,
        timezone_choice,
        interval,
        intervals,
        storage_location,  # xops_data
    )

    # Initialize an empty dictionary for storing the aggregated data
    group_metrics = calculate_group_metrics(record_data)
    print_sorted_person_data(time_records)

    # Now use the updated data list to create CSV
    export_metrics_to_csv(record_data, group_metrics, storage_location, query_mode)


if __name__ == "__main__":
    main()
