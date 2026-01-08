#!/usr/bin/env python3
"""
Fetch epics from Jira by JQL and compute child-issue completion metrics.

Env vars:
  JIRA_SITE            e.g. https://your-domain.atlassian.net
  JIRA_EMAIL           e.g. you@company.com (or USER_EMAIL)
  JIRA_API_TOKEN       Atlassian API token (or JIRA_API_KEY)
  JIRA_EPIC_LABELS     (optional) Comma-separated list of epic labels.
  JIRA_JQL_EPICS       (optional) JQL to select epics. Defaults to:
                       issuetype = Epic AND labels IN ("<LABELS>") AND status IN ("done", "released", "In Progress", "In Develop")
  COMPLETION_STATUSES  (optional) Comma-separated list of statuses to consider as "done".
                       Defaults to "released,done". Example: "released,done,to release,staged release"
                       This affects which child tickets count as completed in the metrics.
  EXCLUDED_STATUSES    (optional) Comma-separated list of statuses to exclude from metrics.
                       Defaults to "closed". Example: "closed,cancelled,duplicate"
                       These tickets don't count as Done (no credit) or Open (not open work).

Usage:
  python epic_tracking.py [options]
  
Options:
  --epic EPIC_KEY        Target specific epic (e.g., PROJ-123)
  --epics EPIC1,EPIC2    Target multiple specific epics
  --quarter YYYY-QN      Analyze completion during specific quarter (e.g., 2024-Q1)
  --month YYYY-MM        Analyze completion during specific month (e.g., 2024-01)
  --year YYYY            Analyze completion during specific year (default: current year)
  --periods N            Show completion data for last N periods (quarters/months)
  -v, --verbose          Enable verbose output
  -csv                   Export to CSV file
  
Examples:
  python epic_tracking.py --epic PROJ-123
  python epic_tracking.py --quarter 2024-Q1 --periods 4  # I.e.  4 periods means 2024-Q1, 2023/Q4,Q3,Q2 -- 4 quarters
  python epic_tracking.py --month 2024-01 --periods 6
  
Output:
  epic_completion.csv in the current directory
  and a summary printed to stdout.
"""

import argparse
import csv
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta

from dotenv import load_dotenv

# Import common utilities from jira_metrics
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "jira_metrics"))
try:
    from jira_utils import (
        JiraStatus,
        extract_status_timestamps,
        get_children_for_epic,
        get_common_parser,
        get_completion_statuses,
        get_excluded_statuses,
        get_team,
        get_ticket_points,
        get_tickets_from_jira,
        interpret_status_timestamps,
        parse_common_arguments,
        verbose_print,
    )
except ImportError:
    # Fallback for when running from different directory
    sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
    from jira_metrics.jira_utils import (
        JiraStatus,
        extract_status_timestamps,
        get_children_for_epic,
        get_common_parser,
        get_completion_statuses,
        get_excluded_statuses,
        get_team,
        get_ticket_points,
        get_tickets_from_jira,
        interpret_status_timestamps,
        parse_common_arguments,
        verbose_print,
    )

# Load environment variables from .env file
load_dotenv()

# ---------- Config via env ----------
SITE = os.environ.get("JIRA_SITE")
EMAIL = os.environ.get("JIRA_EMAIL") or os.environ.get("USER_EMAIL")
API_TOKEN = os.environ.get("JIRA_API_TOKEN") or os.environ.get("JIRA_API_KEY")
# All epic selection is command line based - no environment variables needed

# We'll validate these in main() using a proper validation function


def validate_env_variables():
    """Validate required environment variables and return their values."""
    required_vars = {
        "JIRA_SITE": "Jira server URL (e.g., https://your-domain.atlassian.net)",
        "JIRA_EMAIL or USER_EMAIL": "Jira email address",
        "JIRA_API_TOKEN or JIRA_API_KEY": "Jira API token",
    }

    optional_vars = {
        "JIRA_EPIC_LABELS": "Comma-separated list of epic labels",
        "JIRA_JQL_EPICS": "Custom JQL query for selecting epics",
    }

    missing_vars = []
    env_values = {}

    # Check for required variables with fallbacks
    if not SITE:
        missing_vars.append("JIRA_SITE (Jira server URL)")
    if not EMAIL:
        missing_vars.append("JIRA_EMAIL or USER_EMAIL (Jira email address)")
    if not API_TOKEN:
        missing_vars.append("JIRA_API_TOKEN or JIRA_API_KEY (Jira API token)")

    env_values = {
        "JIRA_SITE": SITE,
        "EMAIL": EMAIL,
        "API_TOKEN": API_TOKEN,
    }

    if missing_vars:
        print("ERROR: Missing required environment variables:")
        for var in missing_vars:
            print(f"  - {var}")
        print("\nOptional environment variables:")
        for var, description in optional_vars.items():
            value = os.environ.get(var, "NOT SET")
            print(f"  - {var}: {value} ({description})")
        print("\nPlease set the required variables in your .env file or environment.")
        sys.exit(1)

    return env_values


def get_quarter_dates(year, quarter):
    """Get start and end dates for a quarter."""
    from datetime import timezone

    quarter_starts = {1: (1, 1), 2: (4, 1), 3: (7, 1), 4: (10, 1)}
    quarter_ends = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}

    start_month, start_day = quarter_starts[quarter]
    end_month, end_day = quarter_ends[quarter]

    start_date = datetime(year, start_month, start_day, tzinfo=timezone.utc)
    end_date = datetime(year, end_month, end_day, 23, 59, 59, tzinfo=timezone.utc)

    return start_date, end_date


def get_month_dates(year, month):
    """Get start and end dates for a month."""
    from datetime import timezone

    start_date = datetime(year, month, 1, tzinfo=timezone.utc)

    # Get last day of month
    if month == 12:
        end_date = datetime(year + 1, 1, 1, tzinfo=timezone.utc) - timedelta(days=1)
    else:
        end_date = datetime(year, month + 1, 1, tzinfo=timezone.utc) - timedelta(days=1)

    end_date = end_date.replace(hour=23, minute=59, second=59)
    return start_date, end_date


def generate_time_periods(time_period):
    """Generate list of time periods to analyze."""
    periods = []

    if time_period["type"] == "quarter":
        year = time_period["year"]
        quarter = time_period["quarter"]

        for i in range(time_period["periods"]):
            current_quarter = quarter - i
            current_year = year

            # Handle year rollover
            while current_quarter <= 0:
                current_quarter += 4
                current_year -= 1

            start_date, end_date = get_quarter_dates(current_year, current_quarter)
            periods.append(
                {"label": f"{current_year}-Q{current_quarter}", "start": start_date, "end": end_date, "type": "quarter"}
            )

    elif time_period["type"] == "month":
        year = time_period["year"]
        month = time_period["month"]

        for i in range(time_period["periods"]):
            current_month = month - i
            current_year = year

            # Handle year rollover
            while current_month <= 0:
                current_month += 12
                current_year -= 1

            start_date, end_date = get_month_dates(current_year, current_month)
            periods.append(
                {"label": f"{current_year}-{current_month:02d}", "start": start_date, "end": end_date, "type": "month"}
            )

    else:  # year
        from datetime import timezone

        year = time_period["year"]
        start_date = datetime(year, 1, 1, tzinfo=timezone.utc)
        end_date = datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
        periods.append({"label": str(year), "start": start_date, "end": end_date, "type": "year"})

    return periods


def get_completion_date(child):
    """Get the completion date for a child ticket (when it was marked Done or Released)."""
    try:
        status_timestamps = extract_status_timestamps(child)
        key_statuses = interpret_status_timestamps(status_timestamps)

        # Check for Released first, then Done
        completion_date = key_statuses.get(JiraStatus.RELEASED.value) or key_statuses.get(JiraStatus.DONE.value)
        return completion_date
    except Exception as e:
        verbose_print(f"Error getting completion date for {child.key}: {e}")
        return None


def bucket_counts_and_points_with_periods(children, time_periods):
    """Calculate ticket counts and story points for Done vs Open vs Excluded buckets, plus time period analysis."""
    total_tickets = len(children)
    done_tickets = 0
    open_tickets = 0
    excluded_tickets = 0
    total_points = 0
    done_points = 0
    open_points = 0
    excluded_points = 0

    # Initialize period tracking
    period_data = {}
    for period in time_periods:
        period_data[period["label"]] = {"tickets_completed": 0, "points_completed": 0}

    # Get completion and excluded statuses from configuration
    completion_statuses = get_completion_statuses()
    excluded_statuses = get_excluded_statuses()

    for child in children:
        # Use the proper status name from the converted issue object
        status_name = (child.fields.status.name or "").strip().lower()

        # Use the existing jira_utils function to get story points
        try:
            points = get_ticket_points(child)
        except AttributeError as e:
            verbose_print(f"Warning: Could not get story points for {child.key}: {e}")
            points = 0
        total_points += points

        # Check if ticket should be excluded (closed, cancelled, etc.)
        is_excluded = status_name in excluded_statuses
        is_done = status_name in completion_statuses

        if is_excluded:
            excluded_tickets += 1
            excluded_points += points
        elif is_done:
            done_tickets += 1
            done_points += points

            # Check which time period this ticket was completed in
            completion_date = get_completion_date(child)
            if completion_date:
                for period in time_periods:
                    if period["start"] <= completion_date <= period["end"]:
                        period_data[period["label"]]["tickets_completed"] += 1
                        period_data[period["label"]]["points_completed"] += points
                        break
        else:
            open_tickets += 1
            open_points += points

    # Calculate percentages excluding the excluded tickets
    active_tickets = total_tickets - excluded_tickets
    active_points = total_points - excluded_points

    tickets_pct_done = round((done_tickets / active_tickets) * 100, 1) if active_tickets else 0.0
    points_pct_done = round((done_points / active_points) * 100, 1) if active_points else 0.0

    return (
        total_tickets,
        done_tickets,
        open_tickets,
        excluded_tickets,
        tickets_pct_done,
        total_points,
        done_points,
        open_points,
        excluded_points,
        points_pct_done,
        period_data,
    )


def build_stdout_header(time_periods):
    """Construct the human-friendly stdout header, including optional period columns.

    Note: the main output uses `build_stdout_table_lines()` to compute column widths
    from both headers and data so long Status values don't shift numeric columns.
    This header helper remains for compatibility with any external usage.
    """
    lines = build_stdout_table_lines([], time_periods)
    return lines[0] if lines else ""


def _underscoreize_header_label(label: str) -> str:
    return label.replace(" ", "_")


def build_stdout_table_lines(
    rows,
    time_periods,
    *,
    column_gap: int = 2,
    summary_gap: int = 4,
    underscore_headers: bool = True,
):
    """Build aligned stdout table lines (header, separator, rows).

    Column widths are computed from the max cell width across all rows so the
    numeric columns stay aligned even when Status/Team/Epic values are long.
    """

    def format_cell(value, formatter):
        if value is None:
            return ""
        if formatter is None:
            return str(value)
        return formatter(value)

    columns = [
        {"key": "epic_key", "label": "Epic", "align": "left", "min_width": 10, "fmt": None},
        {"key": "team", "label": "Team", "align": "left", "min_width": 8, "fmt": None},
        {"key": "status", "label": "Status", "align": "left", "min_width": 12, "fmt": None},
        {"key": "tickets_total", "label": "Total", "align": "right", "min_width": 5, "fmt": None},
        {"key": "tickets_done", "label": "Done", "align": "right", "min_width": 4, "fmt": None},
        {"key": "tickets_open", "label": "Open", "align": "right", "min_width": 5, "fmt": None},
        {"key": "tickets_excluded", "label": "Excl", "align": "right", "min_width": 4, "fmt": None},
        {
            "key": "tickets_percent_done",
            "label": "% Done",
            "align": "right",
            "min_width": 7,
            "fmt": lambda v: f"{v:.1f}",
        },
        {"key": "points_total", "label": "Pts Total", "align": "right", "min_width": 9, "fmt": None},
        {"key": "points_done", "label": "Pts Done", "align": "right", "min_width": 8, "fmt": None},
        {"key": "points_open", "label": "Pts Open", "align": "right", "min_width": 9, "fmt": None},
        {"key": "points_excluded", "label": "Pts Excl", "align": "right", "min_width": 8, "fmt": None},
        {
            "key": "points_percent_done",
            "label": "Pts % Done",
            "align": "right",
            "min_width": 11,
            "fmt": lambda v: f"{v:.1f}",
        },
    ]

    if len(time_periods) > 1:
        for period in reversed(time_periods):
            label = period["label"]
            columns.append(
                {
                    "key": f"{label}_tickets_completed",
                    "label": f"{label} Tix",
                    "align": "right",
                    "min_width": 8,
                    "fmt": None,
                }
            )
            columns.append(
                {
                    "key": f"{label}_points_completed",
                    "label": f"{label} Pts",
                    "align": "right",
                    "min_width": 8,
                    "fmt": None,
                }
            )

    gap = " " * max(1, column_gap)
    summary_separator = " " * max(1, summary_gap)

    header_labels = []
    for col in columns:
        label = col["label"]
        header_labels.append(_underscoreize_header_label(label) if underscore_headers else label)

    widths = []
    for col, header_label in zip(columns, header_labels):
        width = max(col.get("min_width", 0), len(header_label))
        for row in rows:
            cell = format_cell(row.get(col["key"]), col.get("fmt"))
            width = max(width, len(cell))
        widths.append(width)

    def format_row(values):
        formatted = []
        for col, width in zip(columns, widths):
            cell = values.get(col["key"], "")
            if col["align"] == "right":
                formatted.append(cell.rjust(width))
            else:
                formatted.append(cell.ljust(width))
        return gap.join(formatted)

    header_values = {col["key"]: label for col, label in zip(columns, header_labels)}
    header_line = format_row(header_values) + summary_separator + "Summary"

    body_lines = []
    for row in rows:
        values = {}
        for col in columns:
            values[col["key"]] = format_cell(row.get(col["key"]), col.get("fmt"))
        summary = row.get("epic_description", "") or ""
        body_lines.append(format_row(values) + summary_separator + summary)

    separator_line = "-" * len(header_line)
    return [header_line, separator_line, *body_lines]


def build_csv_fieldnames(time_periods):
    """Construct the CSV fieldnames, including dynamic period columns."""
    base_fieldnames = [
        "epic_key",
        "team",
        "epic_description",
        "status",
        "tickets_total",
        "tickets_done",
        "tickets_open",
        "tickets_excluded",
        "tickets_percent_done",
        "points_total",
        "points_done",
        "points_open",
        "points_excluded",
        "points_percent_done",
    ]

    period_fieldnames = []
    for period in time_periods:
        period_label = period["label"]
        period_fieldnames.extend([f"{period_label}_tickets_completed", f"{period_label}_points_completed"])

    return base_fieldnames + period_fieldnames


def get_epic_team(epic):
    """Return team name for an epic using jira_utils.get_team with project fallback.

    Centralizes error handling to avoid duplication across sorting and row rendering.
    """
    try:
        return get_team(epic)
    except Exception as e:  # pylint: disable=broad-except
        verbose_print(f"Warning: Could not get team for {epic.key}: {e}")
        return epic.fields.project.key if getattr(epic.fields, "project", None) else "Unknown"


def test_api_connection():
    """Test basic API connectivity with a simple bounded query."""
    verbose_print("Testing API connection...")

    try:
        # Simple bounded test query to get just one issue from the last 30 days
        test_jql = "created >= -30d ORDER BY created DESC"
        test_result = get_tickets_from_jira(test_jql)

        if test_result:
            verbose_print(f"✓ API connection successful. Test issue: {test_result[0].key}")
            return True
        else:
            verbose_print("✓ API connection successful but no recent issues found")
            return True  # Connection works, just no data

    except Exception as e:
        print(f"✗ API connection test failed: {e}")
        return False


def show_usage_and_exit():
    """Show usage information and exit when no arguments are provided."""
    print("\n" + "=" * 80)
    print("EPIC TRACKING - Arguments Required")
    print("=" * 80)
    print("\nYou must specify BOTH:")
    print("  1. Epic selection (which epics to analyze)")
    print("  2. Time period (when to analyze completion)")
    print("\n📋 Epic Selection (choose one):")
    print("   --epic PROJ-123              Target specific epic")
    print("   --epics PROJ-123,PROJ-456    Target multiple epics")
    print("   --label 2024-Q1              Filter epics by single label")
    print("   --labels 2024-Q1,feature     Filter epics by multiple labels")
    print("\n📅 Time Period (choose one):")
    print("   --quarter 2024-Q1            Analyze specific quarter")
    print("   --month 2024-01              Analyze specific month")
    print("   --year 2024                  Analyze specific year")
    print("\n🔧 Additional Options:")
    print("   --periods N                  Show completion timeline for last N periods")
    print("                                (shows when tickets were actually completed)")
    print("                                Default: 4 quarters, 6 months, 1 year")
    print("   -v, --verbose                Verbose output")
    print("   -csv                         Export to CSV")
    print("\n💡 Examples:")
    print("   # Single epic with default periods (4 quarters)")
    print("   python3 epic_tracking.py --epic PROJ-123 --quarter 2024-Q4")
    print("   ")
    print("   # Multiple epics with 6 months of completion timeline")
    print("   python3 epic_tracking.py --epics PROJ-123,PROJ-456 --month 2024-01 --periods 6")
    print("   ")
    print("   # Filter by label with 2 quarters of completion data")
    print("   python3 epic_tracking.py --label 2025-Q3 --quarter 2024-Q4 --periods 2")
    print("   ")
    print("   # Multiple labels for full year analysis")
    print("   python3 epic_tracking.py --labels 2024-Q1,feature --year 2024")
    print("\n" + "=" * 80)
    sys.exit(1)


def parse_epic_arguments():
    """Parse command line arguments specific to epic tracking."""
    parser = get_common_parser()
    parser.description = "Fetch epics from Jira by JQL and compute child-issue completion metrics."

    # Epic selection arguments (required)
    epic_group = parser.add_mutually_exclusive_group(required=True)
    epic_group.add_argument("--epic", help="Target specific epic key (e.g., PROJ-123)")
    epic_group.add_argument("--epics", help="Target multiple epic keys (comma-separated)")
    epic_group.add_argument("--label", help="Filter epics by single label (e.g., 2024-Q1)")
    epic_group.add_argument("--labels", help="Filter epics by multiple labels (comma-separated)")

    # Time period arguments (required)
    time_group = parser.add_mutually_exclusive_group(required=True)
    time_group.add_argument("--quarter", help="Analyze specific quarter (e.g., 2024-Q1)")
    time_group.add_argument("--month", help="Analyze specific month (e.g., 2024-01)")
    time_group.add_argument("--year", type=int, help="Analyze specific year")

    parser.add_argument(
        "--periods",
        type=int,
        help="Show completion timeline for last N periods going backwards from your specified time period. Shows when tickets were actually completed (marked Done/Released) during each period. Default: 4 for quarters, 6 for months, 1 for years. Example: --quarter 2024-Q4 --periods 4 shows completion data for 2024-Q1, Q2, Q3, Q4",
    )

    return parse_common_arguments(parser)


def build_epic_jql(args):
    """Build JQL query based on command line arguments."""
    if args.epic:
        return f"key = {args.epic}"
    elif args.epics:
        epic_keys = [key.strip() for key in args.epics.split(",") if key.strip()]
        epic_list = ", ".join(epic_keys)
        return f"key in ({epic_list})"
    elif args.label:
        return f'issuetype = Epic AND labels = "{args.label}"'
    elif args.labels:
        label_list = [label.strip() for label in args.labels.split(",") if label.strip()]
        labels_jql = ", ".join(f'"{label}"' for label in label_list)
        return f"issuetype = Epic AND labels IN ({labels_jql})"
    else:
        # This shouldn't happen with required arguments, but just in case
        raise ValueError("No epic selection method specified")


def parse_time_period(args):
    """Parse time period arguments and return period info."""
    if args.quarter:
        # Parse quarter format: YYYY-QN
        try:
            year_str, quarter_str = args.quarter.split("-Q")
            year = int(year_str)
            quarter = int(quarter_str)
            if quarter not in [1, 2, 3, 4]:
                raise ValueError("Quarter must be 1, 2, 3, or 4")
            periods = args.periods if args.periods else 4  # Default: 4 quarters
            return {"type": "quarter", "year": year, "quarter": quarter, "periods": periods}
        except (ValueError, IndexError) as e:
            raise ValueError(f"Invalid quarter format. Use YYYY-QN (e.g., 2024-Q1): {e}")

    elif args.month:
        # Parse month format: YYYY-MM
        try:
            year_str, month_str = args.month.split("-")
            year = int(year_str)
            month = int(month_str)
            if month not in range(1, 13):
                raise ValueError("Month must be 1-12")
            periods = args.periods if args.periods else 6  # Default: 6 months
            return {"type": "month", "year": year, "month": month, "periods": periods}
        except (ValueError, IndexError) as e:
            raise ValueError(f"Invalid month format. Use YYYY-MM (e.g., 2024-01): {e}")

    elif args.year:
        # Specific year
        periods = args.periods if args.periods else 1  # Default: 1 year
        return {"type": "year", "year": args.year, "periods": periods}

    else:
        # This shouldn't happen with required arguments, but just in case
        raise ValueError("No time period specified")


def display_analysis_target(epic_jql, time_period, args):
    """Display what we're analyzing at startup."""
    print("\n" + "=" * 80)
    print("EPIC TRACKING ANALYSIS")
    print("=" * 80)

    print(f"\n📋 Epic Selection:")
    if args.epic:
        print(f"   Single Epic: {args.epic}")
    elif args.epics:
        print(f"   Multiple Epics: {args.epics}")
    elif args.label:
        print(f"   Epic Label: {args.label}")
        print(f"   JQL Query: {epic_jql}")
    elif args.labels:
        print(f"   Epic Labels: {args.labels}")
        print(f"   JQL Query: {epic_jql}")

    print(f"\n📅 Time Period Analysis:")
    if time_period["type"] == "quarter":
        print(f"   Quarter: {time_period['year']}-Q{time_period['quarter']}")
        if time_period["periods"] > 1:
            print(f"   Completion timeline: {time_period['periods']} quarters (shows when tickets were completed)")
    elif time_period["type"] == "month":
        print(f"   Month: {time_period['year']}-{time_period['month']:02d}")
        if time_period["periods"] > 1:
            print(f"   Completion timeline: {time_period['periods']} months (shows when tickets were completed)")
    else:
        print(f"   Year: {time_period['year']}")

    print(f"\n🔧 Environment Variables:")
    env_vars = [
        ("JIRA_SITE", SITE, "Jira server URL"),
        ("JIRA_EMAIL/USER_EMAIL", EMAIL, "Jira email address"),
        ("JIRA_API_TOKEN/JIRA_API_KEY", "***" if API_TOKEN else None, "Jira API token"),
    ]

    for var_name, var_value, description in env_vars:
        if var_value:
            if "API" in var_name and var_value != "***":
                display_value = "*** (set)"
            else:
                display_value = var_value
            print(f"   ✓ {var_name}: {display_value}")
        else:
            print(f"   ⚠️  {var_name}: (not set - {description})")

    # Print completion statuses configuration early
    print(f"\n📊 Completion Configuration:")
    print(f"   ", end="")
    get_completion_statuses()  # This will print the completion statuses
    print(f"   ", end="")
    get_excluded_statuses()  # This will print the excluded statuses

    print("\n" + "=" * 80 + "\n")


def main():
    # Parse command line arguments
    args = parse_epic_arguments()

    # Validate environment variables first
    validate_env_variables()

    # Build JQL and parse time period
    try:
        epic_jql = build_epic_jql(args)
        time_period = parse_time_period(args)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Display what we're analyzing
    display_analysis_target(epic_jql, time_period, args)

    verbose_print(f"Using JQL for epics: {epic_jql}")

    # Test API connection first
    if not test_api_connection():
        print("ERROR: Cannot connect to JIRA API. Please check your credentials and network connection.")
        sys.exit(1)

    # Get epics using the built JQL
    epics = get_tickets_from_jira(epic_jql)
    if not epics:
        print("No epics found for JQL:", epic_jql)
        return

    # Sort epics by team (with project key fallback) and then by epic key
    def get_epic_sort_key(epic):
        team = get_epic_team(epic)
        return (team, epic.key)

    epics.sort(key=get_epic_sort_key)

    # Generate time periods for analysis
    time_periods = generate_time_periods(time_period)

    rows = []
    print(f"Found {len(epics)} epics. Computing completion metrics...\n")

    for epic in epics:
        epic_key = epic.key
        epic_summary = getattr(epic.fields, "summary", "") or ""
        epic_status = epic.fields.status.name

        # Get team name (or project key as fallback)
        epic_team = get_epic_team(epic)

        children = get_children_for_epic(epic_key)
        verbose_print(f"Epic {epic_key}: Found {len(children)} child issues")

        (
            total_tickets,
            done_tickets,
            open_tickets,
            excluded_tickets,
            tickets_pct_done,
            total_points,
            done_points,
            open_points,
            excluded_points,
            points_pct_done,
            period_data,
        ) = bucket_counts_and_points_with_periods(children, time_periods)

        # Build row data for CSV
        row_data = {
            "epic_key": epic_key,
            "team": epic_team,
            "epic_description": epic_summary,
            "status": epic_status,
            "tickets_total": total_tickets,
            "tickets_done": done_tickets,
            "tickets_open": open_tickets,
            "tickets_excluded": excluded_tickets,
            "tickets_percent_done": tickets_pct_done,
            "points_total": total_points,
            "points_done": done_points,
            "points_open": open_points,
            "points_excluded": excluded_points,
            "points_percent_done": points_pct_done,
        }

        # Add period data to CSV row
        for period in time_periods:
            period_label = period["label"]
            row_data[f"{period_label}_tickets_completed"] = period_data[period_label]["tickets_completed"]
            row_data[f"{period_label}_points_completed"] = period_data[period_label]["points_completed"]

        rows.append(row_data)

    for line in build_stdout_table_lines(rows, time_periods):
        print(line)

    # Export to CSV if requested or by default
    out_path = os.path.abspath("epic_completion.csv")

    # Build dynamic fieldnames including time periods
    all_fieldnames = build_csv_fieldnames(time_periods)

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=all_fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nExported data to: {out_path}")
    verbose_print(f"Total epics processed: {len(epics)}")


if __name__ == "__main__":
    main()
