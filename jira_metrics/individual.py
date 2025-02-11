import os
import sys
from calendar import month_abbr
from collections import defaultdict
from datetime import datetime
import csv
from dotenv import load_dotenv

from jira_utils import (
    get_tickets_from_jira,
    get_common_parser,
    verbose_print,
    JiraStatus,
    interpret_status_timestamps,
    extract_status_timestamps,
    get_ticket_points,
    get_team,
)

load_dotenv()


# 1) story points
# completed story points per individual
# average story points in the team
# ratio of individual story points to the average story points

# 2 ) completed tickets
# completed tickets per individual
# average completed tickets in the team
# ratio of individual completed tickets to the average completed tickets

# 3) individual time per point to complete ticket.
# Average time per point to complete ticket in the team

# 4) Number of PRs reviewed per individual
# Average PRs reviewed in the team
# Review throughness ? (comments given, time to address comments in their own PRs)
# Ratio of individual PRs reviewed to the average PRs reviewed


# Global variable for verbosity
CUSTOM_FIELD_STORYPOINTS = os.getenv("CUSTOM_FIELD_STORYPOINTS")
projects = os.environ.get("JIRA_PROJECTS").split(",")


def parse_arguments():
    # pylint: disable=global-statement
    # Define the argument parser
    parser = get_common_parser()
    parser.add_argument(
        "-team",
        required=True,
        help="Specify the team name to process. `python3 -team <teamName>`",
    )
    args = parser.parse_args()
    global VERBOSE
    VERBOSE = args.verbose
    return args


def calculate_points(issue):
    # Assuming the points are stored in a custom field named 'customfield_12345'
    return getattr(issue.fields, f"customfield_{CUSTOM_FIELD_STORYPOINTS}") or 0


def calculate_individual_jira_metrics(start_date, end_date, team_name):

    jql_query = construct_jql(team_name, start_date, end_date)
    tickets = get_tickets_from_jira(jql_query)
    metrics_per_month = defaultdict(lambda: defaultdict(lambda: {"points": 0, "tickets": 0}))
    assignee_metrics = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {"points": 0, "tickets": 0})))

    for _, issue in enumerate(tickets):
        history = extract_status_timestamps(issue)
        statuses = interpret_status_timestamps(history)
        released_timestamp = statuses.get(JiraStatus.RELEASED.value)
        if not released_timestamp:
            released_timestamp = statuses.get(JiraStatus.DONE.value)
            verbose_print(
                f"Warning: Issue {issue.key} does not have a released timestamp. Using Done timestamp instead."
            )
        if not released_timestamp:
            sys.exit("Fatal error: Released ticket, missing released timestamp and done timestamp.")

        team = get_team(issue)
        if team.lower() != team_name:
            print(f"Skipping issue {issue.key} as it does not belong to team {team_name}")
            continue
        assignee_raw = issue.fields.assignee
        assignee = assignee_raw.displayName if assignee_raw else "Unassigned"
        month_key = released_timestamp.strftime("%Y-%m")
        points = get_ticket_points(issue)

        metrics_per_month[month_key][team]["points"] += points
        metrics_per_month[month_key][team]["tickets"] += 1
        assignee_metrics[month_key][team][assignee]["points"] += points
        assignee_metrics[month_key][team][assignee]["tickets"] += 1

        verbose_print(f"Processed issue {issue.key}: {points} points for ({team}) {assignee} in {month_key}")

    return metrics_per_month, assignee_metrics


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


def calculate_rolling_top_contributors(assignee_metrics, end_date):
    end_date = datetime.strptime(end_date, "%Y-%m-%d")

    # Get the last three months (including the end_date month)
    months = sorted(assignee_metrics.keys())[-3:]

    rolling_window_ratios = defaultdict(lambda: {"points": [], "tickets": []})
    total_metrics = defaultdict(lambda: {"points": 0, "tickets": 0})

    for month in months:
        # for team, assignees in assignee_metrics[month].items():
        for _, assignees in assignee_metrics[month].items():
            team_total_points = sum(assignee["points"] for assignee in assignees.values())
            team_total_tickets = sum(assignee["tickets"] for assignee in assignees.values())
            team_size = len(assignees)
            team_average_points = team_total_points / team_size if team_size > 0 else 0
            team_average_tickets = team_total_tickets / team_size if team_size > 0 else 0

            for assignee, metrics in assignees.items():
                if team_average_points > 0:
                    points_ratio = metrics["points"] / team_average_points
                    rolling_window_ratios[assignee]["points"].append(points_ratio)
                if team_average_tickets > 0:
                    tickets_ratio = metrics["tickets"] / team_average_tickets
                    rolling_window_ratios[assignee]["tickets"].append(tickets_ratio)
                total_metrics[assignee]["points"] += metrics["points"]
                total_metrics[assignee]["tickets"] += metrics["tickets"]

    # Calculate average ratios over the 3-month period for each assignee
    average_ratios = {"points": {}, "tickets": {}}

    for assignee, ratios in rolling_window_ratios.items():
        if ratios["points"]:
            average_ratios["points"][assignee] = sum(ratios["points"]) / len(ratios["points"])
        if ratios["tickets"]:
            average_ratios["tickets"][assignee] = sum(ratios["tickets"]) / len(ratios["tickets"])

    # Sort by average ratio and get top 3 for both metrics
    top_contributors = {
        "points": [
            (assignee, ratio, total_metrics[assignee]["points"])
            for assignee, ratio in sorted(average_ratios["points"].items(), key=lambda x: x[1], reverse=True)[:3]
        ],
        "tickets": [
            (assignee, ratio, total_metrics[assignee]["tickets"])
            for assignee, ratio in sorted(average_ratios["tickets"].items(), key=lambda x: x[1], reverse=True)[:3]
        ],
    }

    return top_contributors


def construct_jql(team_name, start_date, end_date):
    if team_name.lower() == "mobile":
        return f'project = MOB AND status in (Released) AND status changed to Released during ("{start_date}", "{end_date}") AND issueType in (Task, Bug, Story, Spike) ORDER BY updated ASC'
    elif team_name.lower() == "devops":
        return f'project = DevOps AND status IN ("Released", "Done")  AND (status changed TO ("Released", "Done") during ({start_date}, {end_date}) AND issuetype IN (Task, Bug, Story, Spike)) ORDER BY updated ASC'
    else:
        return f"project in ({', '.join(projects)}) AND status in (Released) AND status changed to Released during (\"{start_date}\", \"{end_date}\") AND issueType in (Task, Bug, Story, Spike) AND \"Team[Dropdown]\" = \"{team_name}\" ORDER BY updated ASC"


def transform_month(month):
    # Extract the month part and convert it to abbreviated month name
    return month_abbr[int(month)]


def write_csv(assignee_metrics, output_file):
    with open(output_file, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)

        # Get all unique months and sort them
        all_months = sorted(set(month for month in assignee_metrics.keys()))
        current_year = all_months[0].split("-")[0] if all_months else "Year"

        # Transform month names
        transformed_months = [transform_month(month) for month in all_months]

        # Write Points data
        writer.writerow([f"{current_year} Assignee Points"] + transformed_months)
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
        writer.writerow([f"{current_year} Assignee Tickets"] + transformed_months)
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


def main():
    args = parse_arguments()
    current_year = datetime.now().year
    start_date = f"{current_year}-01-01"
    end_date = f"{current_year}-12-31"
    team_name = args.team
    metrics_per_month, assignee_metrics = calculate_individual_jira_metrics(start_date, end_date, team_name)
    process_and_display_metrics(metrics_per_month, assignee_metrics)

    # Calculate and display rolling top contributors based on average ratios
    top_contributors = calculate_rolling_top_contributors(assignee_metrics, end_date)

    print("\nTop 3 contributors over the last 3 months based on average ratio to team performance:")

    print("\nBased on Story Points:")
    for i, (contributor, avg_ratio, total_points) in enumerate(top_contributors["points"], 1):
        print(f"{i}. {contributor}[{total_points}]: Average ratio of {avg_ratio:.2f}")

    print("\nBased on Number of Tickets:")
    for i, (contributor, avg_ratio, total_tickets) in enumerate(top_contributors["tickets"], 1):
        print(f"{i}. {contributor}[{total_tickets}]: Average ratio of {avg_ratio:.2f}")

    if args.csv:
        csv_output_file = f"{team_name}_individual_metrics.csv"
        write_csv(assignee_metrics, csv_output_file)
    else:
        print("CSV output disabled. Use -csv flag to enable.")


if __name__ == "__main__":
    main()
