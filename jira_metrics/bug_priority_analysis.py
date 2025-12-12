# jira_metrics/bug_priority_analysis.py
"""
Bug Priority Analysis Script - Company Specific - the custom fileds will differ. 

Analyzes bugs by priority level, focusing on:
1. Average time from creation to release/completion by priority
2. Count of tickets by priority level

Only analyzes bugs that:
- Have a "Bug Priority" field defined (not empty)
- Are in completed status (Released/Done based on COMPLETION_STATUSES)
"""

import os
import sys
import argparse
import csv
from datetime import datetime
from collections import defaultdict
from dotenv import load_dotenv

# Import utilities from the generic jira_utils
from jira_utils import (
    get_tickets_from_jira,
    get_completion_statuses,
    verbose_print,
    print_env_variables,
    parse_common_arguments,
    get_common_parser
)

load_dotenv()

# Company-specific configuration
CUSTOM_FIELD_BUG_PRIORITY = os.getenv("CUSTOM_FIELD_BUG_PRIORITY")


def setup_logging():
    """Configure logging settings."""
    print("Setting up Bug Priority Analysis...")
    print("=" * 50)
    return None


def validate_env_variables():
    """Validate required environment variables for bug priority analysis."""
    required_vars = {
        "JIRA_API_KEY": "Jira API token",
        "USER_EMAIL": "Jira username", 
        "JIRA_LINK": "Jira server URL",
        "CUSTOM_FIELD_BUG_PRIORITY": "Bug Priority custom field ID",
    }

    missing_vars = []
    env_values = {}

    for var, description in required_vars.items():
        value = os.environ.get(var)
        if not value:
            missing_vars.append(f"{var} ({description})")
        env_values[var] = value

    if missing_vars:
        print("Missing required environment variables:")
        for var in missing_vars:
            print(f"- {var}")
        print("\nPlease set these variables in your .env file.")
        raise ValueError("Missing required environment variables")

    return env_values


def parse_arguments():
    """Parse and validate command line arguments."""
    parser = get_common_parser()
    parser.description = "Analyze bug performance by priority level"
    
    parser.add_argument("--start-date", type=str, required=True, 
                       help="Start date for analysis (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, required=True,
                       help="End date for analysis (YYYY-MM-DD)")
    parser.add_argument("--all-projects", action="store_true",
                       help="Analyze ALL projects (ignores JIRA_PROJECTS env var)")
    
    return parser.parse_args()


def build_jql_query(start_date, end_date, all_projects=False):
    """Build JQL query for bug priority analysis."""
    # Get completion statuses from generic utility
    completion_statuses = get_completion_statuses()
    completion_clause = ",".join(f'"{status.title()}"' for status in completion_statuses)
    
    jql_parts = [
        "issuetype = Bug",
        f"created >= '{start_date}'",
        f"created <= '{end_date}'", 
        f"status IN ({completion_clause})",
        f"cf[{CUSTOM_FIELD_BUG_PRIORITY}] IS NOT EMPTY"
    ]
    
    # Add project filter if not analyzing all projects
    if not all_projects:
        projects = os.getenv("JIRA_PROJECTS", "")
        if projects:
            jql_parts.append(f"project in ({projects})")
    
    return " AND ".join(jql_parts)


def get_bug_priority(ticket):
    """Extract bug priority from ticket, handling different field formats."""
    try:
        priority_field = getattr(ticket.fields, f"customfield_{CUSTOM_FIELD_BUG_PRIORITY}")
        
        if not priority_field:
            return None
            
        # Handle different field formats
        if hasattr(priority_field, 'value'):
            return priority_field.value
        elif isinstance(priority_field, dict) and 'value' in priority_field:
            return priority_field['value']
        elif isinstance(priority_field, str):
            return priority_field
        else:
            verbose_print(f"Unknown priority field format for {ticket.key}: {type(priority_field)}")
            return str(priority_field)
            
    except AttributeError:
        verbose_print(f"Bug priority field not found for ticket {ticket.key}")
        return None


def calculate_time_to_completion(ticket):
    """Calculate time from creation to completion in days."""
    try:
        # Find creation date from changelog - look for the earliest entry (creation event)
        created_date = None
        
        if hasattr(ticket, 'changelog') and hasattr(ticket.changelog, 'histories'):
            # Changelog is in reverse chronological order, so the last entry is creation
            histories = ticket.changelog.histories
            if histories:
                # The last history entry should be the creation
                creation_history = histories[-1]
                try:
                    created_date = datetime.strptime(creation_history.created, "%Y-%m-%dT%H:%M:%S.%f%z")
                    verbose_print(f"{ticket.key}: Found creation date from changelog: {created_date}")
                except ValueError as e:
                    verbose_print(f"Could not parse creation date from changelog for {ticket.key}: {creation_history.created} - {e}")
                    
        # Fallback: try standard fields if changelog method fails
        if not created_date:
            created_str = None
            if hasattr(ticket.fields, 'created') and ticket.fields.created:
                created_str = ticket.fields.created
            elif hasattr(ticket.fields, 'customfield_10018') and ticket.fields.customfield_10018:
                created_str = ticket.fields.customfield_10018
                
            if created_str:
                try:
                    created_date = datetime.strptime(created_str, "%Y-%m-%dT%H:%M:%S.%f%z")
                except ValueError:
                    try:
                        if created_str.endswith('Z'):
                            created_str = created_str[:-1] + '+00:00'
                        created_date = datetime.fromisoformat(created_str)
                    except ValueError as e:
                        verbose_print(f"Could not parse creation date for {ticket.key}: {created_str} - {e}")
                        
        if not created_date:
            verbose_print(f"No creation date found for {ticket.key}")
            return None
        
        # Get completion date from status history
        completion_statuses = [status.lower() for status in get_completion_statuses()]
        completion_date = None
        
        # Look through changelog for most recent completion
        if hasattr(ticket, 'changelog') and hasattr(ticket.changelog, 'histories'):
            for history in ticket.changelog.histories:
                for item in history.items:
                    if (item.field == "status" and 
                        item.toString and 
                        item.toString.lower() in completion_statuses):
                        
                        # Parse completion date using the same format as jira_utils.py
                        try:
                            history_date = datetime.strptime(history.created, "%Y-%m-%dT%H:%M:%S.%f%z")
                        except ValueError:
                            # Fallback for different formats
                            try:
                                history_date_str = history.created
                                if history_date_str.endswith('Z'):
                                    history_date_str = history_date_str[:-1] + '+00:00'
                                history_date = datetime.fromisoformat(history_date_str)
                            except ValueError:
                                verbose_print(f"Could not parse completion date for {ticket.key}: {history.created}")
                                continue
                        
                        # Keep the most recent completion (first in changelog)
                        if not completion_date:
                            completion_date = history_date
                            break
                            
                if completion_date:
                    break
        
        if not completion_date:
            verbose_print(f"No completion date found for {ticket.key}")
            return None
            
        # Calculate difference in days
        time_diff = completion_date - created_date
        return round(time_diff.total_seconds() / (24 * 3600), 2)  # Convert to days
        
    except Exception as e:
        verbose_print(f"Error calculating time to completion for {ticket.key}: {e}")
        return None


def analyze_bug_priorities(tickets):
    """Analyze tickets by bug priority."""
    priority_stats = defaultdict(lambda: {
        'count': 0,
        'completion_times': [],
        'tickets': []
    })
    
    skipped_no_priority = 0
    skipped_no_completion_time = 0
    
    for ticket in tickets:
        priority = get_bug_priority(ticket)
        
        if not priority:
            skipped_no_priority += 1
            verbose_print(f"Skipping {ticket.key}: No bug priority defined")
            continue
            
        completion_time = calculate_time_to_completion(ticket)
        
        if completion_time is None:
            skipped_no_completion_time += 1
            verbose_print(f"Skipping {ticket.key}: Could not calculate completion time")
            continue
            
        # Store the data
        priority_stats[priority]['count'] += 1
        priority_stats[priority]['completion_times'].append(completion_time)
        priority_stats[priority]['tickets'].append({
            'key': ticket.key,
            'completion_time': completion_time,
            'summary': getattr(ticket.fields, 'summary', 'No summary')[:60] + '...'
        })
        
        verbose_print(f"Processed {ticket.key}: Priority={priority}, Time={completion_time} days")
    
    print(f"\nProcessing Summary:")
    print(f"- Total tickets processed: {len(tickets)}")
    print(f"- Skipped (no priority): {skipped_no_priority}")
    print(f"- Skipped (no completion time): {skipped_no_completion_time}")
    print(f"- Successfully analyzed: {sum(stats['count'] for stats in priority_stats.values())}")
    
    return dict(priority_stats)


def display_results(priority_stats):
    """Display analysis results."""
    if not priority_stats:
        print("\nNo data to display. Check that:")
        print("1. Bugs exist in the date range")
        print("2. Bugs have the Bug Priority field set")
        print("3. Bugs are in completed status")
        return
        
    print("\n" + "=" * 80)
    print("BUG PRIORITY ANALYSIS RESULTS")
    print("=" * 80)
    
    # Sort priorities by count (descending)
    sorted_priorities = sorted(priority_stats.items(), 
                             key=lambda x: x[1]['count'], 
                             reverse=True)
    
    total_bugs = sum(stats['count'] for stats in priority_stats.values())
    
    print(f"\nOverall Summary:")
    print(f"- Total bugs analyzed: {total_bugs}")
    print(f"- Priority levels found: {len(priority_stats)}")
    
    print(f"\nResults by Priority Level:")
    print(f"{'Priority':<20} {'Count':<8} {'%':<6} {'Avg Days':<10} {'Min':<8} {'Max':<8}")
    print("-" * 70)
    
    for priority, stats in sorted_priorities:
        count = stats['count']
        times = stats['completion_times']
        
        avg_time = sum(times) / len(times) if times else 0
        min_time = min(times) if times else 0
        max_time = max(times) if times else 0
        percentage = (count / total_bugs * 100) if total_bugs > 0 else 0
        
        print(f"{priority:<20} {count:<8} {percentage:<5.1f}% {avg_time:<9.1f} {min_time:<7.1f} {max_time:<7.1f}")
    
    # Show detailed breakdown for verbose mode
    if os.getenv('VERBOSE'):
        print(f"\nDetailed Breakdown:")
        for priority, stats in sorted_priorities:
            print(f"\n{priority} ({stats['count']} tickets):")
            for ticket_info in stats['tickets'][:5]:  # Show first 5
                print(f"  {ticket_info['key']}: {ticket_info['completion_time']} days - {ticket_info['summary']}")
            if len(stats['tickets']) > 5:
                print(f"  ... and {len(stats['tickets']) - 5} more")


def export_to_csv(priority_stats, filename):
    """Export results to CSV file."""
    if not priority_stats:
        print("No data to export")
        return
        
    with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        
        # Write summary data
        writer.writerow(['Priority', 'Count', 'Average_Days', 'Min_Days', 'Max_Days', 'Median_Days'])
        
        for priority, stats in priority_stats.items():
            times = stats['completion_times']
            if times:
                avg_time = sum(times) / len(times)
                min_time = min(times)
                max_time = max(times)
                median_time = sorted(times)[len(times) // 2]
                
                writer.writerow([priority, stats['count'], 
                               round(avg_time, 2), round(min_time, 2), 
                               round(max_time, 2), round(median_time, 2)])
        
        # Write detailed ticket data
        writer.writerow([])  # Empty row
        writer.writerow(['Ticket_Key', 'Priority', 'Completion_Days', 'Summary'])
        
        for priority, stats in priority_stats.items():
            for ticket_info in stats['tickets']:
                writer.writerow([ticket_info['key'], priority, 
                               ticket_info['completion_time'], 
                               ticket_info['summary']])
    
    print(f"\nResults exported to: {filename}")


def main():
    """Main function for bug priority analysis."""
    try:
        setup_logging()
        
        # Parse arguments and validate environment
        args = parse_arguments()
        env_vars = validate_env_variables()
        
        # Set verbose mode
        global VERBOSE
        from jira_utils import VERBOSE
        
        print_env_variables()
        
        # Build and execute query
        jql_query = build_jql_query(args.start_date, args.end_date, args.all_projects)
        
        print(f"\nJQL Query:")
        print(f"{jql_query}")
        print(f"\nFetching tickets...")
        
        tickets = get_tickets_from_jira(jql_query)
        
        if not tickets:
            print("No tickets found matching the criteria")
            return
            
        print(f"Retrieved {len(tickets)} tickets for analysis")
        
        # Analyze by priority
        priority_stats = analyze_bug_priorities(tickets)
        
        # Display results
        display_results(priority_stats)
        
        # Export to CSV if requested
        if args.csv:
            filename = f"bug_priority_analysis_{args.start_date}_to_{args.end_date}.csv"
            export_to_csv(priority_stats, filename)
            
    except Exception as e:
        print(f"\nError: {str(e)}")
        if VERBOSE:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
