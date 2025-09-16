#!/usr/bin/env python3
"""
epic_completion.py
Fetch epics from Jira by JQL and compute child-issue completion metrics.

Env vars:
  JIRA_SITE            e.g. https://your-domain.atlassian.net
  JIRA_EMAIL           e.g. you@company.com (or USER_EMAIL)
  JIRA_API_TOKEN       Atlassian API token (or JIRA_API_KEY)
  JIRA_EPIC_LABELS     (optional) Comma-separated list of epic labels. 
  JIRA_JQL_EPICS       (optional) JQL to select epics. Defaults to:
                       issuetype = Epic AND labels IN ("<LABELS>") AND status IN ("done", "released", "In Progress", "In Develop")

Usage:
  python epic_completion.py
Output:
  epic_completion.csv in the current directory
  and a summary printed to stdout.
"""

import csv
import os
import sys
import time
import argparse
from typing import Dict, List, Any
import requests
from dotenv import load_dotenv

# Import common utilities from jira_metrics
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "jira_metrics"))
try:
    from jira_utils import get_common_parser, parse_common_arguments, verbose_print
except ImportError:
    # Fallback for when running from different directory
    sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
    from jira_metrics.jira_utils import get_common_parser, parse_common_arguments, verbose_print

# Load environment variables from .env file
load_dotenv()

# ---------- Config via env ----------
SITE = os.environ.get("JIRA_SITE")
EMAIL = os.environ.get("JIRA_EMAIL") or os.environ.get("USER_EMAIL")
API_TOKEN = os.environ.get("JIRA_API_TOKEN") or os.environ.get("JIRA_API_KEY")
# Get labels from environment variable
EPIC_LABELS = os.environ.get("JIRA_EPIC_LABELS")

# Build default JQL with proper labels IN syntax
if EPIC_LABELS and EPIC_LABELS.strip():
    # Convert comma-separated labels to proper JQL format
    labels_list = [label.strip() for label in EPIC_LABELS.split(",") if label.strip()]
    if labels_list:  # Only add labels clause if we have actual labels
        labels_jql = ", ".join(f'"{label}"' for label in labels_list)
        default_jql = (
            f'issuetype = Epic AND labels IN ({labels_jql}) AND status IN ("done", "released", "In Progress", "In Develop")'
        )
    else:
        default_jql = 'issuetype = Epic AND status IN ("done", "released", "In Progress", "In Develop")'
else:
    default_jql = 'issuetype = Epic AND status IN ("done", "released", "In Progress", "In Develop")'

JQL_EPICS = os.environ.get("JIRA_JQL_EPICS", default_jql)

# We'll validate these in main() using a proper validation function

# Jira REST API v3 - Updated endpoint as per migration guide
if SITE:
    API_SEARCH = f"{SITE}/rest/api/3/search/jql"
else:
    API_SEARCH = None

# Buckets (lowercase status names compared against these sets)
DONE_STATUSES = {"done", "released"}
INPROG_STATUSES = {"in progress", "in develop"}


# ---------- Helpers ----------
def _req_get(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """GET with basic auth + simple retry on 429/5xx - following GitHub API patterns."""
    verbose_print(f"Making request to: {url}")
    verbose_print(f"Request params: {params}")
    
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    for attempt in range(5):
        try:
            r = requests.get(
                url, 
                params=params, 
                auth=(EMAIL, API_TOKEN),
                headers=headers,
                timeout=30
            )
            verbose_print(f"Response status: {r.status_code}")
            
            if r.status_code in (429, 500, 502, 503, 504):
                wait = min(2**attempt, 10)
                verbose_print(f"Rate limited or server error, waiting {wait}s...")
                time.sleep(wait)
                continue
            
            if r.status_code != 200:
                print(f"ERROR: Request failed with status {r.status_code}")
                print(f"URL: {r.url}")
                print(f"Response: {r.text[:500]}")  # Limit response text
                
            r.raise_for_status()
            return r.json()
            
        except requests.exceptions.RequestException as e:
            if attempt == 4:  # Last attempt
                raise
            wait = min(2**attempt, 10)
            verbose_print(f"Request exception: {e}. Retrying in {wait}s...")
            time.sleep(wait)
    
    # This shouldn't be reached, but just in case
    r.raise_for_status()
    return r.json()


def search_jql(jql: str, fields: List[str], max_per_page: int = 100) -> List[Dict[str, Any]]:
    """Paginate through search results using JIRA REST API v3."""
    if not API_SEARCH:
        raise ValueError("API_SEARCH endpoint not configured - check JIRA_SITE environment variable")
        
    verbose_print(f"Executing JQL: {jql}")
    verbose_print(f"Requested fields: {fields}")
    
    issues: List[Dict[str, Any]] = []
    start_at = 0
    
    while True:
        params = {
            "jql": jql,
            "startAt": start_at,
            "maxResults": max_per_page,
            "fields": ",".join(fields),
        }
        
        page = _req_get(API_SEARCH, params)
        
        if not page:
            verbose_print("No response data received")
            break
            
        page_issues = page.get("issues", [])
        issues.extend(page_issues)
        
        verbose_print(f"Page retrieved: {len(page_issues)} issues (total so far: {len(issues)})")
        
        start_at += len(page_issues)
        total = page.get("total", 0)
        
        verbose_print(f"Progress: {start_at}/{total}")
        
        if start_at >= total or len(page_issues) == 0:
            break
            
    verbose_print(f"JQL search completed: {len(issues)} total issues found")
    return issues


def get_epics() -> List[Dict[str, Any]]:
    fields = ["summary", "status"]
    issues = search_jql(JQL_EPICS, fields)
    return issues


def get_children_for_epic(epic_key: str) -> List[Dict[str, Any]]:
    """Get child issues for an epic (works for company-managed and team-managed)."""
    # We explicitly exclude Epics here and allow any standard child type
    jql = f'issuetype != Epic AND ("Epic Link" = {epic_key} OR parent = {epic_key})'
    fields = ["summary", "status"]
    return search_jql(jql, fields)


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


def bucket_counts(children: List[Dict[str, Any]]):
    total = len(children)
    done = 0
    inprog = 0
    other = 0
    for c in children:
        status_name = (c["fields"]["status"]["name"] or "").strip().lower()
        if status_name in DONE_STATUSES:
            done += 1
        elif status_name in INPROG_STATUSES:
            inprog += 1
        else:
            other += 1
    pct_done = round((done / total) * 100, 1) if total else 0.0
    return total, done, inprog, other, pct_done


def test_api_connection():
    """Test basic API connectivity with a simple bounded query."""
    verbose_print("Testing API connection...")
    
    try:
        # Simple bounded test query to get just one issue from the last 30 days
        test_jql = "created >= -30d ORDER BY created DESC"
        test_result = search_jql(test_jql, ["key"], max_per_page=1)
        
        if test_result:
            verbose_print(f"✓ API connection successful. Test issue: {test_result[0].get('key', 'unknown')}")
            return True
        else:
            verbose_print("✓ API connection successful but no recent issues found")
            return True  # Connection works, just no data
            
    except Exception as e:
        print(f"✗ API connection test failed: {e}")
        return False


def main():
    # Parse command line arguments
    parser = get_common_parser()
    parser.description = "Fetch epics from Jira by JQL and compute child-issue completion metrics."
    args = parse_common_arguments(parser)

    # Validate environment variables first
    validate_env_variables()

    verbose_print(f"Using JQL for epics: {JQL_EPICS}")
    
    # Test API connection first
    if not test_api_connection():
        print("ERROR: Cannot connect to JIRA API. Please check your credentials and network connection.")
        sys.exit(1)

    epics = get_epics()
    if not epics:
        print("No epics found for JQL:", JQL_EPICS)
        return

    rows = []
    print(f"Found {len(epics)} epics. Computing completion metrics...\n")
    print(
        f"{'Epic':10}  {'Status':12}  {'Total':>5}  {'Done/Rel':>8}  {'InProg/Dev':>10}  {'Other':>5}  {'% Done':>7}  {'Summary'}"
    )
    print("-" * 100)

    for e in epics:
        epic_key = e["key"]
        fields = e["fields"]
        epic_summary = fields.get("summary", "") or ""
        epic_status = fields["status"]["name"]

        children = get_children_for_epic(epic_key)
        verbose_print(f"Epic {epic_key}: Found {len(children)} child issues")
        total, done, inprog, other, pct_done = bucket_counts(children)

        print(
            f"{epic_key:10}  {epic_status:12}  {total:5d}  {done:8d}  {inprog:10d}  {other:5d}  {pct_done:7.1f}  {epic_summary}"
        )

        rows.append(
            {
                "epic_key": epic_key,
                "epic_description": epic_summary,
                "status": epic_status,
                "child_count_total": total,
                "child_count_done_released": done,
                "child_count_inprogress_indevelop": inprog,
                "child_count_other": other,
                "percent_done_released": pct_done,
            }
        )

    # Export to CSV if requested or by default
    out_path = os.path.abspath("epic_completion.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "epic_key",
                "epic_description",
                "status",
                "child_count_total",
                "child_count_done_released",
                "child_count_inprogress_indevelop",
                "child_count_other",
                "percent_done_released",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nExported data to: {out_path}")
    verbose_print(f"Total epics processed: {len(epics)}")


if __name__ == "__main__":
    main()
