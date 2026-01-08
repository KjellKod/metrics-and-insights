# jira_metrics/bug_stats.py

import argparse
import csv
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime

from dotenv import load_dotenv

# pylint: disable=import-error
from jira_utils import get_tickets_from_jira, print_env_variables

load_dotenv()  # Add this after imports

# # ==============================================================================
# Easy validation query for open bugs at the end of the year
# issuetype = Bug
# AND created <= "2023-12-31"
# AND status WAS NOT IN ("Done","Closed","Released") ON "2023-12-31"
# # ==============================================================================


def sanitize_projects(raw_projects):
    """Normalize project keys from environment configuration."""
    return [proj.strip().strip("'") for proj in raw_projects.split(",") if proj.strip()]


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


def build_jql_queries(year, projects=None):
    """
    Build JQL queries for different bug metrics.

    Args:
        year: The year to analyze
        projects: Optional list of projects to filter by. If None, queries all projects.
    """
    if projects:
        # Legacy mode: filter by specific projects
        quoted_projects = [f"'{project}'" for project in projects]
        project_clause = f"project in ({', '.join(quoted_projects)}) AND "
    else:
        # New mode: query all projects
        project_clause = ""

    return {
        "created": f"{project_clause}issuetype = Bug AND created >= '{year}-01-01' AND created <= '{year}-12-31'",
        "closed": f"{project_clause}issuetype = Bug AND status IN (Done, Closed, Released) AND status CHANGED TO (Done, Closed, Released) DURING ('{year}-01-01', '{year}-12-31')",
        "open_eoy": (
            f"{project_clause}issuetype = Bug AND created <= '{year}-12-31' "
            f"AND status WAS NOT IN (Done, Closed, Released) ON '{year}-12-31'"
        ),
    }


# pylint: disable=too-many-locals
def fetch_bug_statistics(year, projects, progress_callback=None):
    """
    Fetch bug statistics for a given year, broken down by project.

    Args:
        year: The year to analyze
        projects: List of Jira project keys, or None to discover projects from data
        progress_callback: Optional callback function for progress reporting

    Returns:
        Dictionary containing bug statistics and ticket details, broken down by project
    """
    queries = build_jql_queries(year, projects)
    stats = defaultdict(lambda: defaultdict(dict))
    all_discovered_projects = set()

    # First pass: collect all data and discover all projects
    metric_data = {}
    for metric, query in queries.items():
        tickets = get_tickets_from_jira(query)
        project_counts = defaultdict(int)
        project_tickets = defaultdict(list)

        for ticket in tickets:
            # Defensive check - every ticket MUST have a project
            if not hasattr(ticket.fields, "project") or not ticket.fields.project:
                logger = logging.getLogger(__name__)
                logger.error(
                    "CRITICAL DATA INTEGRITY ERROR: Bug %s has no project! This should be impossible in Jira.",
                    ticket.key,
                )
                logger.error("This indicates a serious problem with Jira data or API permissions.")
                logger.error("Please investigate immediately. Exiting to prevent incorrect statistics.")
                raise RuntimeError(f"Bug {ticket.key} has no project - data integrity violation")

            if not hasattr(ticket.fields.project, "key") or not ticket.fields.project.key:
                logger = logging.getLogger(__name__)
                logger.error(
                    "CRITICAL DATA INTEGRITY ERROR: Bug %s project has no key! Project object: %s",
                    ticket.key,
                    ticket.fields.project,
                )
                logger.error("This indicates a serious problem with Jira data or API permissions.")
                logger.error("Please investigate immediately. Exiting to prevent incorrect statistics.")
                raise RuntimeError(f"Bug {ticket.key} project has no key - data integrity violation")

            # Strip single quotes from the project key to ensure consistency
            project_key = ticket.fields.project.key.strip("'")
            project_counts[project_key] += 1
            project_tickets[project_key].append(ticket.key)
            all_discovered_projects.add(project_key)

        metric_data[metric] = {"project_counts": project_counts, "project_tickets": project_tickets}

        if progress_callback:
            progress_callback(year, metric, len(tickets))

    # Second pass: populate stats for all projects across all metrics
    projects_to_process = projects if projects is not None else sorted(all_discovered_projects)

    for project in projects_to_process:
        for metric in queries.keys():
            project_counts = metric_data[metric]["project_counts"]
            project_tickets = metric_data[metric]["project_tickets"]
            stats[project][metric] = {
                "count": project_counts.get(project, 0),  # Default to 0 if no tickets found
                "tickets": project_tickets.get(project, []),  # Default to empty list if no tickets found
            }

    logger = logging.getLogger(__name__)
    if logger.isEnabledFor(logging.DEBUG):
        for project, metrics in stats.items():
            for metric, data in metrics.items():
                sample = ", ".join(data["tickets"][:5])
                logger.debug(
                    "Project %s metric %s count=%d sample=%s",
                    project,
                    metric,
                    data["count"],
                    sample if sample else "<none>",
                )

    return stats


# pylint: disable=superfluous-parens
def validate_years(start_year, end_year):
    """Validate the provided year range."""
    current_year = datetime.now().year
    max_future_year = current_year + 10  # Allow up to 10 years in the future

    if not (1900 <= start_year <= max_future_year):
        raise ValueError(f"Start year must be between 1900 and {max_future_year}")

    if not (1900 <= end_year <= max_future_year):
        raise ValueError(f"End year must be between 1900 and {max_future_year}")

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
        headers = ["Year", "Total Bugs Created", "Total Bugs Closed", "Bugs Open End of Year"]
        for project in projects:
            headers.append(f"{project} Bugs Created")
        for project in projects:
            headers.append(f"{project} Bugs Closed")
        writer.writerow(headers)

        # Write data rows
        for year in sorted(stats.keys()):
            total_created = sum(stats[year][proj]["created"]["count"] for proj in stats[year])
            total_closed = sum(stats[year][proj]["closed"]["count"] for proj in stats[year])
            open_eoy = sum(stats[year][proj]["open_eoy"]["count"] for proj in stats[year])

            # Initialize project-specific counts
            project_created = {proj: stats[year].get(proj, {}).get("created", {}).get("count", 0) for proj in projects}
            project_closed = {proj: stats[year].get(proj, {}).get("closed", {}).get("count", 0) for proj in projects}

            # Write the row
            row = [year, total_created, total_closed, open_eoy]
            for proj in projects:
                row.append(project_created[proj])
            for proj in projects:
                row.append(project_closed[proj])
            writer.writerow(row)

    print(f"Bug summary exported successfully to {filename}")
    return filename


def parse_arguments():
    """Parse and validate command line arguments."""
    parser = argparse.ArgumentParser(description="Analyze Jira bug statistics")
    parser.add_argument("--start-year", type=int, required=True, help="Start year (YYYY)")
    parser.add_argument("--end-year", type=int, required=True, help="End year (YYYY)")
    parser.add_argument("--csv", action="store_true", help="Export results to CSV")
    parser.add_argument(
        "--all-projects", action="store_true", help="Analyze ALL projects in Jira (ignores JIRA_PROJECTS env var)"
    )
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
        projects: List of Jira project keys, or None to query all projects

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
            logger.info("Bugs open at end of year: %d", stats[year][project]["open_eoy"]["count"])

            # Calculate net change excluding Won't Do
            net_change = stats[year][project]["created"]["count"] - stats[year][project]["closed"]["count"]
            logger.info("Net change in bugs: %d", net_change)

        totals = compute_year_totals(stats[year])
        logger.info("\nAll Projects (%d):", year)
        logger.info("Bugs created: %d", totals["created"])
        logger.info("Bugs closed: %d", totals["closed"])
        logger.info("Bugs open at end of year: %d", totals["open_eoy"])
        logger.info("Net change in bugs: %d", totals["net_change"])


def compute_year_totals(project_stats):
    """Aggregate metrics across all projects for display/export."""
    created = sum(project_stats[proj]["created"]["count"] for proj in project_stats)
    closed = sum(project_stats[proj]["closed"]["count"] for proj in project_stats)
    open_eoy = sum(project_stats[proj]["open_eoy"]["count"] for proj in project_stats)
    return {
        "created": created,
        "closed": closed,
        "open_eoy": open_eoy,
        "net_change": created - closed,
    }


def validate_env_variables(require_projects=True):
    """Validate required environment variables and return their values."""
    logger = logging.getLogger(__name__)
    required_vars = {
        "JIRA_API_KEY": "Jira API token",
        "USER_EMAIL": "Jira username",
        "JIRA_LINK": "Jira server URL",
    }

    optional_vars = {
        "JIRA_PROJECTS": "Comma-separated list of Jira project keys",
    }

    missing_vars = []
    env_values = {}

    # Check required variables
    for var, description in required_vars.items():
        value = os.environ.get(var)
        if not value:
            missing_vars.append(f"{var} ({description})")
        env_values[var] = value

    # Check optional variables
    for var, description in optional_vars.items():
        value = os.environ.get(var)
        if not value and require_projects and var == "JIRA_PROJECTS":
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
        env_vars = validate_env_variables(require_projects=not args.all_projects)
        print_env_variables()  # This will print all environment variables in a consistent way

        if args.all_projects:
            projects = None  # Query all projects
            logger.info("Analyzing bug statistics for ALL projects in Jira")
        else:
            projects = sanitize_projects(env_vars["JIRA_PROJECTS"])
            logger.info("Analyzing bug statistics for configured projects: %s", projects)

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
