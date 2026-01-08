import csv
import os
import sys
import traceback
from calendar import month_abbr
from collections import defaultdict
from datetime import datetime

from dotenv import load_dotenv

# Global variable for verbose mode
VERBOSE = False

# pylint: disable=import-error
from jira_utils import (JiraStatus, extract_status_timestamps,
                        get_common_parser, get_completion_statuses,
                        get_team, get_ticket_points,
                        get_tickets_from_jira, interpret_status_timestamps,
                        verbose_print)

load_dotenv()

# Global variable for verbosity
CUSTOM_FIELD_STORYPOINTS = os.getenv("CUSTOM_FIELD_STORYPOINTS")
projects = os.environ.get("JIRA_PROJECTS").split(",")


def show_usage():
    """Display script usage information"""
    print("\nJIRA Individual Metrics Report")
    print("=============================")
    print("\nThis script analyzes individual contributor metrics from JIRA.")
    print("\nUsage:")
    print("  By team:    python3 jira_metrics/individual.py -team <team_name>")
    print("  By project: python3 jira_metrics/individual.py -project <project_key>")
    print("\nExample:")
    print("  python3 jira_metrics/individual.py -team swedes")
    print("  python3 jira_metrics/individual.py -project SWE")
    print("\nOptional flags:")
    print("  -verbose    Show detailed processing information")
    print("  -csv        Generate CSV report")
    sys.exit(1)


def parse_arguments():
    """Parse and validate command line arguments"""
    if len(sys.argv) == 1:
        show_usage()

    parser = get_common_parser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-team", help="Process metrics for specified team")
    group.add_argument("-project", help="Process metrics for specified project")

    try:
        args = parser.parse_args()
        global VERBOSE
        VERBOSE = args.verbose
        return args
    except Exception as e:
        print(f"\nError: {str(e)}")
        show_usage()


def calculate_points(issue):
    # Assuming the points are stored in a custom field named 'customfield_12345'
    return getattr(issue.fields, f"customfield_{CUSTOM_FIELD_STORYPOINTS}") or 0


# pylint: disable=too-many-locals
def calculate_individual_jira_metrics(start_date, end_date, team_name=None, project_key=None):
    identifier = team_name or project_key
    print(f"\nFetching JIRA data for {team_name and 'team' or 'project'}: {identifier}")
    print(f"Period: {start_date} to {end_date}\n")

    jql_query = construct_jql(team_name, project_key, start_date, end_date)
    print(f"JQL Query: {jql_query}\n")

    tickets = get_tickets_from_jira(jql_query)
    if not tickets:
        print(f"No tickets found for {identifier}")
        sys.exit(1)

    verbose_print(f"Received {len(tickets)} tickets")

    metrics_per_month = defaultdict(lambda: defaultdict(lambda: {"points": 0, "tickets": 0}))
    assignee_metrics = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {"points": 0, "tickets": 0})))

    for _, issue in enumerate(tickets):
        history = extract_status_timestamps(issue)
        statuses = interpret_status_timestamps(history)

        # Get the most recent completion status (Released, Done)
        completion_timestamp = None
        for status in [JiraStatus.RELEASED.value, JiraStatus.DONE.value]:
            if status in statuses and statuses[status] is not None:
                timestamp = statuses[status]
                if completion_timestamp is None or timestamp > completion_timestamp:
                    completion_timestamp = timestamp

        if not completion_timestamp:
            verbose_print(f"Warning: Issue {issue.key} does not have a completion timestamp (Released, Done).")
            continue

        # Handle team identification based on whether we're using team or project
        if team_name:
            team = get_team(issue)
            if team.lower() != team_name.lower():
                verbose_print(f"Skipping issue {issue.key} as it does not belong to team {team_name}")
                continue
        else:
            # When using project, use the project key as the team identifier
            team = project_key

        assignee_raw = issue.fields.assignee
        assignee = assignee_raw.displayName if assignee_raw else "Unassigned"
        month_key = completion_timestamp.strftime("%Y-%m")
        points = get_ticket_points(issue)

        metrics_per_month[month_key][team]["points"] += points
        metrics_per_month[month_key][team]["tickets"] += 1
        assignee_metrics[month_key][team][assignee]["points"] += points
        assignee_metrics[month_key][team][assignee]["tickets"] += 1

        verbose_print(
            f"Processed issue {issue.key}: {points} points for ({team}) {assignee} in {month_key} (Status: {issue.fields.status.name})"
        )

    return metrics_per_month, assignee_metrics


# pylint: disable=too-many-locals
def process_and_display_metrics(metrics_per_month, assignee_metrics):
    for month, metrics in sorted(metrics_per_month.items()):
        print(f"\nMonth: {month}")
        for team, team_metrics in metrics.items():
            team_total_points = team_metrics["points"]
            team_total_tickets = team_metrics["tickets"]
            team_members = assignee_metrics[month][team]
            team_size = len(team_members)

            team_average_points = team_total_points / team_size if team_size > 0 else 0
            team_average_tickets = team_total_tickets / team_size if team_size > 0 else 0

            print(f"Team: {team}")
            print(f"Total Points: {team_total_points}")
            print(f"Total Tickets: {team_total_tickets}")
            print(f"Average Points per Member: {team_average_points:.2f}")
            print(f"Average Tickets per Member: {team_average_tickets:.2f}")

            print("Individual metrics (sorted by points):")
            # Sort team members by points in descending order
            sorted_members = sorted(team_members.items(), key=lambda x: x[1]["points"], reverse=True)
            for assignee, metrics in sorted_members:
                points_ratio = metrics["points"] / team_average_points if team_average_points > 0 else 0
                tickets_ratio = metrics["tickets"] / team_average_tickets if team_average_tickets > 0 else 0
                print(
                    f"{assignee}: Points: {metrics['points']}, Points Ratio: {points_ratio:.2f}, "
                    f"Tickets: {metrics['tickets']}, Tickets Ratio: {tickets_ratio:.2f}"
                )


# pylint: disable=too-many-locals
def calculate_rolling_top_contributors(assignee_metrics, end_date):
    end_date = datetime.strptime(end_date, "%Y-%m-%d")

    # Get the last three months (including the end_date month)
    months = sorted(assignee_metrics.keys())[-3:]

    # Track total metrics across all months
    total_metrics = defaultdict(lambda: {"points": 0, "tickets": 0, "months_active": 0})

    # Track monthly ratios
    monthly_ratios = defaultdict(lambda: {"points": [], "tickets": []})

    # Calculate team totals and averages per month, then individual ratios
    for month in months:
        # Aggregate all assignees across teams if using project filter
        all_assignees = {}
        for _, team_assignees in assignee_metrics[month].items():
            for assignee, metrics in team_assignees.items():
                if assignee not in all_assignees:
                    all_assignees[assignee] = {"points": 0, "tickets": 0}
                all_assignees[assignee]["points"] += metrics["points"]
                all_assignees[assignee]["tickets"] += metrics["tickets"]

                # Add to running totals
                total_metrics[assignee]["points"] += metrics["points"]
                total_metrics[assignee]["tickets"] += metrics["tickets"]

        # Mark this person as active this month
        for assignee, metrics in all_assignees.items():
            if metrics["points"] > 0 or metrics["tickets"] > 0:
                total_metrics[assignee]["months_active"] += 1

        # Calculate team average for this month
        active_assignees = sum(1 for a in all_assignees.values() if a["points"] > 0 or a["tickets"] > 0)
        if active_assignees > 0:
            month_avg_points = sum(a["points"] for a in all_assignees.values()) / active_assignees
            month_avg_tickets = sum(a["tickets"] for a in all_assignees.values()) / active_assignees

            # Calculate ratios for active assignees
            for assignee, metrics in all_assignees.items():
                if metrics["points"] > 0 or metrics["tickets"] > 0:
                    if month_avg_points > 0:
                        monthly_ratios[assignee]["points"].append(metrics["points"] / month_avg_points)
                    if month_avg_tickets > 0:
                        monthly_ratios[assignee]["tickets"].append(metrics["tickets"] / month_avg_tickets)

    # Calculate average ratios over active months
    average_ratios = {"points": {}, "tickets": {}}

    for assignee, ratios in monthly_ratios.items():
        if ratios["points"]:
            average_ratios["points"][assignee] = sum(ratios["points"]) / len(ratios["points"])
        if ratios["tickets"]:
            average_ratios["tickets"][assignee] = sum(ratios["tickets"]) / len(ratios["tickets"])

    # Sort by average ratio and get top 3 for both metrics
    top_contributors = {
        "points_ratio": [
            (assignee, ratio, total_metrics[assignee]["points"])
            for assignee, ratio in sorted(average_ratios["points"].items(), key=lambda x: x[1], reverse=True)[:3]
        ],
        "tickets_ratio": [
            (assignee, ratio, total_metrics[assignee]["tickets"])
            for assignee, ratio in sorted(average_ratios["tickets"].items(), key=lambda x: x[1], reverse=True)[:3]
        ],
        "points_total": [
            (assignee, total_metrics[assignee]["points"])
            for assignee in sorted(total_metrics.keys(), key=lambda x: total_metrics[x]["points"], reverse=True)[:3]
        ],
        "tickets_total": [
            (assignee, total_metrics[assignee]["tickets"])
            for assignee in sorted(total_metrics.keys(), key=lambda x: total_metrics[x]["tickets"], reverse=True)[:3]
        ],
    }

    return top_contributors


# pylint: disable=too-many-locals
def construct_jql(team_name=None, project_key=None, start_date=None, end_date=None):
    # Use configured completion statuses instead of hardcoding
    # Status names with spaces or special words need quotes
    completion_statuses = get_completion_statuses()
    status_list = ", ".join(f'"{status.title()}"' for status in completion_statuses)
    
    # Use uppercase keywords like bug_stats.py does (IN, CHANGED TO, DURING)
    # Use single quotes for dates like bug_stats.py does
    base_jql = f'status IN ({status_list}) AND status CHANGED TO ({status_list}) DURING (\'{start_date}\', \'{end_date}\') AND issueType IN (Task, Bug, Story, Spike)'

    if project_key:
        # Use single quotes around project key like bug_stats.py
        return f"project = '{project_key}' AND {base_jql} ORDER BY updated ASC"

    if team_name:
        # Use single quotes around projects like bug_stats.py
        cleaned_projects = [p.strip().strip("'") for p in projects]
        quoted_projects = [f"'{p}'" for p in cleaned_projects]
        return f'project IN ({", ".join(quoted_projects)}) AND {base_jql} AND "Team[Dropdown]" = "{team_name}" ORDER BY updated ASC'

    raise ValueError("Either team_name or project_key must be provided")


def transform_month(month):
    # Extract the month part and convert it to abbreviated month name
    year, month_str = month.split("-")
    return f"{year} {month_abbr[int(month_str)]}"


def write_csv(assignee_metrics, output_file):
    with open(output_file, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)

        # Get all unique months and sort them
        all_months = sorted(set(month for month in assignee_metrics.keys()))

        # Transform month names
        transformed_months = [transform_month(month) for month in all_months]

        # Write Points data
        writer.writerow(["Assignee Released Points"] + transformed_months)
        all_assignees = set()
        for month_data in assignee_metrics.values():
            for team_data in month_data.values():
                all_assignees.update(team_data.keys())
        for assignee in sorted(all_assignees):
            row_data = [assignee]
            for month in all_months:
                points = 0
                for team_data in assignee_metrics.get(month, {}).values():
                    if assignee in team_data:
                        points += team_data[assignee]["points"]
                row_data.append(points)
            writer.writerow(row_data)

        # Add a couple of blank lines for better readability
        writer.writerow([])
        writer.writerow([])

        # Write Tickets data
        writer.writerow(["Assignee Released Tickets"] + transformed_months)
        for assignee in sorted(all_assignees):
            row_data = [assignee]
            for month in all_months:
                tickets = 0
                for team_data in assignee_metrics.get(month, {}).values():
                    if assignee in team_data:
                        tickets += team_data[assignee]["tickets"]
                row_data.append(tickets)
            writer.writerow(row_data)

    print(f"Writing individual metrics to {output_file}")


def print_year_summary(assignee_metrics):
    """Print year-end summary: total completed tickets and per-person totals."""
    # Aggregate all tickets and points across all months and teams
    total_tickets_year = 0
    total_points_year = 0
    tickets_per_person = defaultdict(int)
    points_per_person = defaultdict(int)

    for month_data in assignee_metrics.values():
        for team_data in month_data.values():
            for assignee, metrics in team_data.items():
                ticket_count = metrics.get("tickets", 0)
                points_count = metrics.get("points", 0)
                total_tickets_year += ticket_count
                total_points_year += points_count
                tickets_per_person[assignee] += ticket_count
                points_per_person[assignee] += points_count

    # Print summary
    print("\n" + "=" * 80)
    print("YEAR-END SUMMARY")
    print("=" * 80)
    print(f"\nTotal Completed Tickets (Year): {total_tickets_year}")
    print(f"Total Completed Points (Year): {total_points_year}")

    if tickets_per_person:
        print(f"\nTotal Completed Tickets per Person:")
        # Sort by ticket count descending
        sorted_persons = sorted(tickets_per_person.items(), key=lambda x: x[1], reverse=True)
        for assignee, ticket_count in sorted_persons:
            points_count = points_per_person[assignee]
            print(f"  {assignee}: {ticket_count} tickets, {points_count} points")
    else:
        print("\nNo tickets found for any person.")


def main():
    args = parse_arguments()
    current_year = "2025" #datetime.now().year
    start_date = f"{current_year}-01-01"
    end_date = f"{current_year}-12-31"

    identifier = args.team if args.team else args.project

    try:
        metrics_per_month, assignee_metrics = calculate_individual_jira_metrics(
            start_date, end_date, team_name=args.team, project_key=args.project
        )

        if not metrics_per_month:
            print(f"No metrics data found for {identifier}")
            sys.exit(1)

        print("\nProcessing metrics data...")
        process_and_display_metrics(metrics_per_month, assignee_metrics)

        # Calculate and display top contributors
        print("\nCalculating top contributors...")
        top_contributors = calculate_rolling_top_contributors(assignee_metrics, end_date)

        print("\nTop 3 contributors over the last 3 months based on average ratio to team performance:")

        print("\nBased on Story Points Ratio (relative to team average):")
        for i, (contributor, avg_ratio, total_points) in enumerate(top_contributors["points_ratio"], 1):
            print(f"{i}. {contributor}[{total_points}]: Average ratio of {avg_ratio:.2f}")

        print("\nBased on Number of Tickets Ratio (relative to team average):")
        for i, (contributor, avg_ratio, total_tickets) in enumerate(top_contributors["tickets_ratio"], 1):
            print(f"{i}. {contributor}[{total_tickets}]: Average ratio of {avg_ratio:.2f}")

        print("\nTop 3 contributors over the last 3 months based on absolute output:")

        print("\nBased on Total Story Points:")
        for i, (contributor, total_points) in enumerate(top_contributors["points_total"], 1):
            print(f"{i}. {contributor}: {total_points} points")

        print("\nBased on Total Number of Tickets:")
        for i, (contributor, total_tickets) in enumerate(top_contributors["tickets_total"], 1):
            print(f"{i}. {contributor}: {total_tickets} tickets")

        # Print year-end summary
        print_year_summary(assignee_metrics)

        if args.csv:
            csv_output_file = f"{identifier}_individual_metrics.csv"
            write_csv(assignee_metrics, csv_output_file)
        else:
            print("\nTip: Use -csv flag to generate a CSV report")

    except Exception as e:
        print(f"\nError: {str(e)}")
        if VERBOSE:
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
