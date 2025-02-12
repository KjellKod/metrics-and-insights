# jira_metrics/bug_stats.py

import os
import sys
from collections import defaultdict
from datetime import datetime
import argparse
import logging
import csv
from dotenv import load_dotenv

load_dotenv()  # Add this after imports

from jira_utils import get_jira_instance, get_tickets_from_jira, print_env_variables

def setup_logging():
    """Configure logging settings."""
    print("Setting up logging...")  # Debug print
    
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
        
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    logger = logging.getLogger(__name__)
    logger.info("Logging setup complete")
    print("Logging setup finished")  # Debug print
    return logger

def build_jql_queries(year, projects):
    """
    Build JQL queries for different bug metrics.
    
    Args:
        year: The year to analyze
        projects: List of Jira project keys
    
    Returns:
        Dictionary containing different JQL queries for bug metrics
    """
    project_clause = f"project in ({', '.join(projects)})"
    return {
        'created': f"{project_clause} AND issuetype = Bug AND created >= '{year}-01-01' AND created <= '{year}-12-31'",
        'resolved': f"{project_clause} AND issuetype = Bug AND status in (Done, Closed) AND resolved >= '{year}-01-01' AND resolved <= '{year}-12-31'",
        'open_eoy': f"{project_clause} AND issuetype = Bug AND created <= '{year}-12-31' AND (resolved >= '{year}-12-31' OR resolution = Empty)"
    }

def fetch_bug_statistics(year, projects, progress_callback=None):
    """
    Fetch bug statistics for a given year.
    
    Args:
        year: The year to analyze
        projects: List of Jira project keys
        progress_callback: Optional callback function for progress reporting
    
    Returns:
        Dictionary containing bug statistics and ticket details
    """
    queries = build_jql_queries(year, projects)
    stats = defaultdict(dict)
    
    for metric, query in queries.items():
        tickets = get_tickets_from_jira(query)
        ticket_keys = [ticket.key for ticket in tickets]
        stats[metric] = {
            'count': len(tickets),
            'tickets': ticket_keys
        }
        
        if progress_callback:
            progress_callback(year, metric, len(tickets))
        
    return stats

def validate_years(start_year, end_year):
    """Validate the provided year range."""
    current_year = datetime.now().year
    
    if not (1900 <= start_year <= current_year):
        raise ValueError(f"Start year must be between 1900 and {current_year}")
    
    if not (1900 <= end_year <= current_year):
        raise ValueError(f"End year must be between 1900 and {current_year}")
    
    if start_year > end_year:
        raise ValueError("Start year cannot be greater than end year")

def export_to_csv(stats, filename="bug_statistics.csv"):
    """Export bug statistics to CSV file."""
    with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['Year', 'Metric', 'Count', 'Tickets'])
        
        for year in sorted(stats.keys()):
            for metric in ['created', 'resolved', 'open_eoy']:
                writer.writerow([
                    year,
                    metric,
                    stats[year][metric]['count'],
                    ', '.join(stats[year][metric]['tickets'])
                ])

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
    Generate bug statistics report for the specified year range.
    
    Args:
        start_year: Starting year for analysis
        end_year: Ending year for analysis
        projects: List of Jira project keys
    
    Returns:
        Dictionary containing bug statistics for all years
    """
    validate_years(start_year, end_year)
    yearly_stats = {}
    
    for year in range(start_year, end_year + 1):
        yearly_stats[year] = fetch_bug_statistics(year, projects, progress_callback=log_progress)
        
    return yearly_stats

def display_results(stats, logger):
    """Display bug statistics results."""
    for year in sorted(stats.keys()):
        logger.info("\nStatistics for year %d:", year)
        logger.info("Bugs created: %d", stats[year]['created']['count'])
        logger.info("Bugs resolved: %d", stats[year]['resolved']['count'])
        logger.info("Bugs open at end of year: %d", stats[year]['open_eoy']['count'])
        
        # Display net change in bugs
        net_change = stats[year]['created']['count'] - stats[year]['resolved']['count']
        logger.info("Net change in bugs: %d", net_change)

def validate_env_variables():
    """Validate required environment variables and return their values."""
    logger = logging.getLogger(__name__)
    required_vars = {
        "JIRA_API_KEY": "Jira API token",
        "USER_EMAIL": "Jira username",
        "JIRA_LINK": "Jira server URL",
        "JIRA_PROJECTS": "Comma-separated list of Jira project keys"
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
            export_to_csv(stats)
            logger.info("Results exported to bug_statistics.csv")
            
    except ValueError as e:
        logger.error("Configuration error: %s", str(e))
        sys.exit(1)
    except Exception as e:
        logger.error("An unexpected error occurred: %s", str(e), exc_info=True)
        sys.exit(1)



if __name__ == "__main__":
    main()