# jira_metrics/bug_stats.py

import os
import sys
from collections import defaultdict
from datetime import datetime
import argparse
import logging
import csv
from dotenv import load_dotenv

# pylint: disable=import-error
from jira_utils import get_tickets_from_jira, print_env_variables


load_dotenv()  # Add this after imports


def setup_logging():
    """Configure logging settings."""
    print("Setting up logging...")  # Debug print

    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    logging.basicConfig(
        level=logging.INFO,
        format="\t%(message)s",  # Removed the timestamp ' %(levelname)s format="%(asctime)s ... etc where datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    logger = logging.getLogger(__name__)
    logger.info("Logging setup complete")
    print("Logging setup finished")  # Debug print
    return logger


def build_jql_queries(year, projects):
    """
    Build JQL queries for different bug metrics.
    """
    quoted_projects = [f"'{project.strip(chr(39))}'" for project in projects]
    project_clause = f"project in ({', '.join(quoted_projects)})"
    return {
        "created": f"{project_clause} AND issuetype = Bug AND created >= '{year}-01-01' AND created <= '{year}-12-31'",
        "closed": f"{project_clause} AND issuetype = Bug AND status in (Done, Closed, Released) AND updated >= '{year}-01-01' AND updated <= '{year}-12-31' AND resolution != \"Won't Do\"",
        "open_eoy": f"{project_clause} AND issuetype = Bug AND created <= '{year}-12-31' AND status not in (Done, Closed, Released)",
        "wont_do": f"{project_clause} AND issuetype = Bug AND status in (Done, Closed, Released) AND updated >= '{year}-01-01' AND updated <= '{year}-12-31' AND resolution = \"Won't Do\"",
    }


# pylint: disable=too-many-locals
def fetch_bug_statistics(year, projects, progress_callback=None):
    """
    Fetch bug statistics for a given year, broken down by project.

    Args:
        year: The year to analyze
        projects: List of Jira project keys
        progress_callback: Optional callback function for progress reporting

    Returns:
        Dictionary containing bug statistics and ticket details, broken down by project
    """
    queries = build_jql_queries(year, projects)
    stats = defaultdict(lambda: defaultdict(dict))

    for metric, query in queries.items():
        tickets = get_tickets_from_jira(query)
        project_counts = defaultdict(int)
        project_tickets = defaultdict(list)

        for ticket in tickets:
            # Strip single quotes from the project key to ensure consistency
            project_key = ticket.fields.project.key.strip("'")
            project_counts[project_key] += 1
            project_tickets[project_key].append(ticket.key)

        for project in projects:
            # Strip single quotes from the project key to ensure consistency
            stripped_project = project.strip("'")
            stats[stripped_project][metric] = {
                "count": project_counts.get(stripped_project, 0),  # Default to 0 if no tickets found
                "tickets": project_tickets.get(stripped_project, []),  # Default to empty list if no tickets found
            }

        if progress_callback:
            progress_callback(year, metric, len(tickets))

    # Debug print
    print("Stats dictionary after fetching data:")
    for project, metrics in stats.items():
        print(f"Project: {project}")
        for metric, data in metrics.items():
            print(f"  {metric}: {data}")

    return stats


# pylint: disable=superfluous-parens
def validate_years(start_year, end_year):
    """Validate the provided year range."""
    current_year = datetime.now().year

    if not (1900 <= start_year <= current_year):
        raise ValueError(f"Start year must be between 1900 and {current_year}")

    if not (1900 <= end_year <= current_year):
        raise ValueError(f"End year must be between 1900 and {current_year}")

    if start_year > end_year:
        raise ValueError("Start year cannot be greater than end year")


def export_to_csv(stats, filename="bug_summary.csv"):
    """Export structured bug statistics for easier charting and analysis."""
    with open(filename, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)

        # Dynamically determine the projects from the stats
        projects = set()
        for year in stats.keys():
            projects.update(stats[year].keys())
        projects = sorted(projects)  # Sort for consistent ordering

        # Write headers
        headers = ["Year", "Total Bugs Created", "Total Bugs Closed", "Total Won't Do", "Bugs Open End of Year"]
        for project in projects:
            headers.append(f"{project} Bugs Created")
        for project in projects:
            headers.append(f"{project} Bugs Closed")
        for project in projects:
            headers.append(f"{project} Won't Do")
        writer.writerow(headers)

        # Write data rows
        for year in sorted(stats.keys()):
            total_created = sum(stats[year][proj]["created"]["count"] for proj in stats[year])
            total_closed = sum(stats[year][proj]["closed"]["count"] for proj in stats[year])
            total_wont_do = sum(stats[year][proj]["wont_do"]["count"] for proj in stats[year])
            open_eoy = sum(stats[year][proj]["open_eoy"]["count"] for proj in stats[year])

            # Initialize project-specific counts
            project_created = {proj: stats[year].get(proj, {}).get("created", {}).get("count", 0) for proj in projects}
            project_closed = {proj: stats[year].get(proj, {}).get("closed", {}).get("count", 0) for proj in projects}
            project_wont_do = {proj: stats[year].get(proj, {}).get("wont_do", {}).get("count", 0) for proj in projects}

            # Write the row
            row = [year, total_created, total_closed, total_wont_do, open_eoy]
            for proj in projects:
                row.append(project_created[proj])
            for proj in projects:
                row.append(project_closed[proj])
            for proj in projects:
                row.append(project_wont_do[proj])
            writer.writerow(row)

    print(f"Bug summary exported successfully to {filename}")
    return filename


def parse_arguments():
    """Parse and validate command line arguments."""
    parser = argparse.ArgumentParser(description="Analyze Jira bug statistics")
    parser.add_argument("--start-year", type=int, required=True, help="Start year (YYYY)")
    parser.add_argument("--end-year", type=int, required=True, help="End year (YYYY)")
    parser.add_argument("--csv", action="store_true", help="Export results to CSV")
    return parser.parse_args()


def log_progress(year, metric, count):
    """Callback function for logging progress."""
    logger = logging.getLogger(__name__)
    logger.info("Year %d - %s bugs: %d", year, metric, count)


def generate_yearly_report(start_year, end_year, projects):
    """
    Generate bug statistics report for the specified year range, broken down by project.

    Args:
        start_year: Starting year for analysis
        end_year: Ending year for analysis
        projects: List of Jira project keys

    Returns:
        Dictionary containing bug statistics for all years, broken down by project
    """
    validate_years(start_year, end_year)
    yearly_stats = {}

    for year in range(start_year, end_year + 1):
        yearly_stats[year] = fetch_bug_statistics(year, projects, progress_callback=log_progress)

    return yearly_stats


def display_results(stats, logger):
    """Display bug statistics results, including project-specific data."""
    for year in sorted(stats.keys()):
        logger.info("\nStatistics for year %d:", year)
        for project in sorted(stats[year].keys()):
            logger.info("\nProject: %s", project)
            logger.info("Bugs created: %d", stats[year][project]["created"]["count"])
            logger.info("Bugs closed: %d", stats[year][project]["closed"]["count"])
            logger.info("Bugs marked as Won't Do: %d", stats[year][project]["wont_do"]["count"])
            logger.info("Bugs open at end of year: %d", stats[year][project]["open_eoy"]["count"])

            # Calculate net change excluding Won't Do
            net_change = stats[year][project]["created"]["count"] - (
                stats[year][project]["closed"]["count"] + stats[year][project]["wont_do"]["count"]
            )
            logger.info("Net change in bugs: %d", net_change)


def validate_env_variables():
    """Validate required environment variables and return their values."""
    logger = logging.getLogger(__name__)
    required_vars = {
        "JIRA_API_KEY": "Jira API token",
        "USER_EMAIL": "Jira username",
        "JIRA_LINK": "Jira server URL",
        "JIRA_PROJECTS": "Comma-separated list of Jira project keys",
    }

    missing_vars = []
    env_values = {}

    for var, description in required_vars.items():
        value = os.environ.get(var)
        if not value:
            missing_vars.append(f"{var} ({description})")
        env_values[var] = value

    if missing_vars:
        logger.error("Missing required environment variables:\n%s", "\n".join(f"- {var}" for var in missing_vars))
        raise ValueError("Missing required environment variables")

    return env_values


def main():
    """Main function to run the bug statistics analysis."""
    logger = setup_logging()

    try:
        logger.info("Starting bug statistics analysis...")

        args = parse_arguments()
        env_vars = validate_env_variables()
        print_env_variables()  # This will print all environment variables in a consistent way

        projects = env_vars["JIRA_PROJECTS"].split(",")
        logger.info("Analyzing bug statistics for projects: %s", projects)

        stats = generate_yearly_report(args.start_year, args.end_year, projects)
        display_results(stats, logger)

        if args.csv:
            filename = "bug_statistics.csv"
            export_to_csv(stats, filename)
            logger.info("Results exported to filename: %s", filename)

    except ValueError as e:
        logger.error("Configuration error: %s", str(e))
        sys.exit(1)
    except Exception as e:
        logger.error("An unexpected error occurred: %s", str(e), exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
