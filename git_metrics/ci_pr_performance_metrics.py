import os

import statistics
import json
import argparse
import time
import random
import traceback
from collections import defaultdict
from datetime import datetime
from dotenv import load_dotenv
import requests


# pylint: disable=pointless-string-statement
"""
GitHub PR Metrics Analysis Script

Analyzes Pull Request (PR) metrics including merge times, CI performance, and review patterns.
Data is cached by default to handle rate limits and allow resume capability.

An easy "sanity check" of the produced result can be to use Github's page and view the closed
PRs. Use this filter to see if it corresponds to the results from this script for a given 
time period: `is:pr is:closed is:merged closed:2025-02-01..2025-02-28` 

Examples:
  # Normal run with caching enabled
  python ci_pr_performance_metrics.py

  # Force fresh data fetch, ignoring cache
  python ci_pr_performance_metrics.py --force-fresh

  # Run with verbose output
  python ci_pr_performance_metrics.py -v

  # Load from specific cache file
  python ci_pr_performance_metrics.py --load-from-file my_cache.json

options:
  -h, --help            show this help message and exit
  -v, --verbose        Enable verbose output for debugging
  --force-fresh        Ignore existing cache and fetch fresh data from GitHub. Warning: This may trigger rate limits!
  --load-from-file LOAD_FROM_FILE
                      Load data from a specified cache file instead of querying GitHub
  --save-to-file SAVE_TO_FILE
                      Save retrieved data to a specified file (useful for backup)
  --start-date START_DATE
                      Start date for PR analysis (format: YYYY-MM-DD, default: 2024-01-01)
"""


load_dotenv()

# Global variable for verbosity
VERBOSE = False


def verbose_print(message):
    if VERBOSE:
        print(message)


def get_common_parser():
    parser = argparse.ArgumentParser(
        description="""
GitHub PR Metrics Analysis Script

Analyzes Pull Request (PR) metrics including merge times, CI performance, and review patterns.
Data is cached by default to handle rate limits and allow resume capability.

Examples:
  # Normal run with caching enabled
  python ci_pr_performance_metrics.py

  # Force fresh data fetch, ignoring cache
  python ci_pr_performance_metrics.py --force-fresh

  # Run with verbose output
  python ci_pr_performance_metrics.py -v

  # Load from specific cache file
  python ci_pr_performance_metrics.py --load-from-file my_cache.json
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,  # This preserves formatting in description
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output for debugging",
    )

    parser.add_argument(
        "--force-fresh",
        action="store_true",
        help="Ignore existing cache and fetch fresh data from GitHub. Warning: This may trigger rate limits!",
    )

    parser.add_argument(
        "--load-from-file",
        type=str,
        help="Load data from a specified cache file instead of querying GitHub",
    )

    parser.add_argument(
        "--save-to-file",
        type=str,
        help="Save retrieved data to a specified file (useful for backup)",
    )

    parser.add_argument(
        "--start-date",
        type=str,
        default="2024-01-01",
        help="Start date for PR analysis (format: YYYY-MM-DD, default: 2024-01-01)",
    )

    return parser


def parse_common_arguments(parser=None):
    if parser is None:
        parser = get_common_parser()
    global VERBOSE
    args = parser.parse_args()
    VERBOSE = args.verbose
    print(f"Verbose printing enabled: {VERBOSE}")
    return args  # Make sure it's returning args, not the parser


def load_from_file(filename):
    verbose_print(f"Loading data from {filename}")
    if not os.path.exists(filename):
        print(f"File {filename} does not exist.")
        return None
    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list) or not all(isinstance(pr, dict) for pr in data):
            print(f"Invalid data structure in {filename}")
            return None
        return data
    except json.JSONDecodeError:
        print(f"Error decoding JSON from {filename}")
        return None


def save_to_file(data, filename):
    verbose_print(f"Saving data to {filename}")
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f)
        print(f"Saved data to {filename}")
    except IOError:
        print(f"Error writing to {filename}")


def validate_environment():
    """Validates required environment variables are present."""
    required_vars = {
        "GITHUB_TOKEN_READONLY_WEB": "GitHub API token",
        "GITHUB_METRIC_OWNER_OR_ORGANIZATION": "GitHub owner/organization name",
        "GITHUB_METRIC_REPO": "GitHub repository name",
    }

    missing_vars = []
    for var, description in required_vars.items():
        if not os.environ.get(var):
            missing_vars.append(f"{var} ({description})")

    if missing_vars:
        raise EnvironmentError(
            "Missing required environment variables:\n"
            + "\n".join(f"- {var}" for var in missing_vars)
            + "\nPlease set these variables in your .env file or environment."
        )


def setup_github_api():
    """Sets up GitHub API configuration after validating environment variables."""
    validate_environment()

    return {
        "access_token": os.environ["GITHUB_TOKEN_READONLY_WEB"],
        "owner": os.environ["GITHUB_METRIC_OWNER_OR_ORGANIZATION"],
        "repo": os.environ["GITHUB_METRIC_REPO"],
        "headers": {
            "Authorization": f"token {os.environ['GITHUB_TOKEN_READONLY_WEB']}",
            "Accept": "application/vnd.github.v3+json",
        },
    }


def get_single_pull_request(pr_number):
    url = f"{base_url}/pulls/{pr_number}"
    response = requests.get(url, headers=headers, timeout=30)
    return [response.json()] if response.status_code == 200 else []


def get_graphql_query():
    return """
    query($owner: String!, $repo: String!, $cursor: String) {
      repository(owner: $owner, name: $repo) {
        pullRequests(
          first: 25,  # Reduced from 100
          after: $cursor,
          orderBy: {field: UPDATED_AT, direction: DESC},
          states: [MERGED]
        ) {
          pageInfo {
            hasNextPage
            endCursor
          }
          nodes {
            number
            title
            createdAt
            mergedAt
            additions
            deletions
            changedFiles
            labels(first: 10) {  # Reduced from 100
              nodes {
                name
              }
            }
            reviews(first: 10) {  # Reduced from 100
              totalCount
              nodes {
                state
                createdAt
                author {
                  login
                }
              }
            }
            comments {  # Removed first parameter, just get count
              totalCount
            }
            commits(last: 1) {
              totalCount
              nodes {
                commit {
                  checkSuites(first: 10) {  # Reduced from 100
                    nodes {
                      checkRuns(first: 10) {  # Reduced from 100
                        nodes {
                          name
                          startedAt
                          completedAt
                          status
                          conclusion
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
    """


def exponential_backoff(attempt, max_delay=60):
    """Calculate exponential backoff delay."""
    delay = min(max_delay, (2**attempt) + random.uniform(0, 1))
    return delay


def execute_graphql_query(query, variables, attempt=0, max_attempts=5):
    """Execute a GraphQL query with retry logic."""
    if attempt >= max_attempts:
        raise Exception("Max retry attempts reached")

    try:
        # Add small delay between requests to avoid hitting rate limits
        time.sleep(1)  # 1 second baseline delay

        url = "https://api.github.com/graphql"
        headers = {
            "Authorization": f"Bearer {os.environ['GITHUB_TOKEN_READONLY_WEB']}",
            "Accept": "application/vnd.github.v3+json",
        }

        response = requests.post(url, json={"query": query, "variables": variables}, headers=headers)

        if response.status_code == 403:
            delay = exponential_backoff(attempt)
            print(f"Rate limit hit. Waiting {delay:.1f} seconds before retry...")
            time.sleep(delay)
            return execute_graphql_query(query, variables, attempt + 1, max_attempts)

        response.raise_for_status()
        return response.json()

    except requests.exceptions.RequestException as e:
        delay = exponential_backoff(attempt)
        print(f"Request failed: {e}. Retrying in {delay:.1f} seconds...")
        time.sleep(delay)
        return execute_graphql_query(query, variables, attempt + 1, max_attempts)


def get_pull_requests(start_date):
    """Fetch PRs using GraphQL with caching and resume capability."""
    query = get_graphql_query()
    prs = []
    cursor = None
    start_datetime = datetime.strptime(start_date, "%Y-%m-%dT%H:%M:%SZ")

    # Load cache if exists
    cache_file = "pr_cache.json"
    if os.path.exists(cache_file):
        with open(cache_file, "r", encoding="utf-8") as f:
            cache_data = json.load(f)
            prs = cache_data.get("prs", [])
            cursor = cache_data.get("cursor", None)
            print(f"Loaded {len(prs)} PRs from cache")

    try:
        while True:
            variables = {
                "owner": os.environ["GITHUB_METRIC_OWNER_OR_ORGANIZATION"],
                "repo": os.environ["GITHUB_METRIC_REPO"],
                "cursor": cursor,
            }

            print(f"Fetching PRs with cursor: {cursor}")
            result = execute_graphql_query(query, variables)

            if not result.get("data") or not result["data"].get("repository"):
                print(f"Unexpected response structure: {result}")
                break

            data = result["data"]["repository"]["pullRequests"]

            if not data.get("nodes"):
                print("No PR nodes found in response")
                break

            found_old_pr = False
            for pr in data["nodes"]:
                if not pr.get("mergedAt"):
                    continue

                merged_at = datetime.strptime(pr["mergedAt"], "%Y-%m-%dT%H:%M:%SZ")
                if merged_at >= start_datetime:
                    prs.append(pr)
                    print(f"Added PR #{pr['number']}, merged at {pr['mergedAt']}")
                else:
                    print(f"Reached PR merged before start date: {pr['mergedAt']}")
                    found_old_pr = True
                    break

            # Save progress to cache
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump({"prs": prs, "cursor": cursor}, f)

            if found_old_pr or not data["pageInfo"].get("hasNextPage"):
                break

            cursor = data["pageInfo"].get("endCursor")

        print(f"Retrieved {len(prs)} PRs merged since {start_date}")
        return prs

    except Exception as e:
        print(f"Error fetching PRs: {e}")
        raise


# pylint: disable=too-many-locals
def calculate_metrics(prs):
    """Calculate enhanced metrics from GraphQL data."""
    pr_metrics = defaultdict(list)

    for pr in prs:
        pr_number = pr["number"]

        # Check if PR was approved
        reviews = pr["reviews"]["nodes"]
        was_approved = any(review["state"] == "APPROVED" for review in reviews)

        if not was_approved:
            continue

        created_at = datetime.strptime(pr["createdAt"], "%Y-%m-%dT%H:%M:%SZ")
        merged_at = datetime.strptime(pr["mergedAt"], "%Y-%m-%dT%H:%M:%SZ")
        merge_time = merged_at - created_at
        merge_month = merged_at.strftime("%Y-%m")

        # Calculate check times
        total_check_time_seconds = 0
        failed_checks = 0
        successful_checks = 0

        if pr["commits"]["nodes"]:
            commit = pr["commits"]["nodes"][0]["commit"]
            for suite in commit["checkSuites"]["nodes"]:
                for check_run in suite["checkRuns"]["nodes"]:
                    if check_run["startedAt"] and check_run["completedAt"]:
                        started_at = datetime.strptime(check_run["startedAt"], "%Y-%m-%dT%H:%M:%SZ")
                        completed_at = datetime.strptime(check_run["completedAt"], "%Y-%m-%dT%H:%M:%SZ")
                        check_duration = (completed_at - started_at).total_seconds()
                        total_check_time_seconds += check_duration

                        if check_run["conclusion"] == "SUCCESS":
                            successful_checks += 1
                        elif check_run["conclusion"] in ["FAILURE", "CANCELLED"]:
                            failed_checks += 1

        # Calculate review metrics
        first_review_time = None
        total_reviews = len(reviews)
        review_time_seconds = 0

        if reviews:
            reviews.sort(key=lambda x: x["createdAt"])
            first_review = reviews[0]
            first_review_time = datetime.strptime(first_review["createdAt"], "%Y-%m-%dT%H:%M:%SZ")
            review_time_seconds = (first_review_time - created_at).total_seconds()

        pr_metrics[merge_month].append(
            {
                "pr_number": pr_number,
                "merge_time": merge_time.total_seconds(),
                "total_check_time": total_check_time_seconds,
                "code_changes": {
                    "additions": pr["additions"],
                    "deletions": pr["deletions"],
                    "changed_files": pr["changedFiles"],
                },
                "reviews": {
                    "count": total_reviews,
                    "time_to_first_review": (review_time_seconds if first_review_time else None),
                },
                "checks": {"successful": successful_checks, "failed": failed_checks},
                "comments": pr["comments"]["totalCount"],
            }
        )

    return pr_metrics


# pylint: disable=too-many-locals
def get_merged_prs_for_years(start_year, end_year):
    """Get yearly PR counts using GraphQL."""
    query = """
    query($owner: String!, $repo: String!, $cursor: String) {
      repository(owner: $owner, name: $repo) {
        pullRequests(
          first: 100,
          after: $cursor,
          orderBy: {field: CREATED_AT, direction: DESC},
          states: [MERGED]
        ) {
          pageInfo {
            hasNextPage
            endCursor
          }
          nodes {
            number
            createdAt
            mergedAt
          }
        }
      }
    }
    """

    year_counts = {year: 0 for year in range(start_year, end_year + 1)}
    cursor = None

    while True:
        variables = {
            "owner": os.environ["GITHUB_METRIC_OWNER_OR_ORGANIZATION"],
            "repo": os.environ["GITHUB_METRIC_REPO"],
            "cursor": cursor,
        }

        result = execute_graphql_query(query, variables)
        data = result["data"]["repository"]["pullRequests"]

        for pr in data["nodes"]:
            merged_year = datetime.strptime(pr["mergedAt"], "%Y-%m-%dT%H:%M:%SZ").year
            created_year = datetime.strptime(pr["createdAt"], "%Y-%m-%dT%H:%M:%SZ").year

            if created_year < start_year:
                return year_counts

            if start_year <= merged_year <= end_year:
                year_counts[merged_year] += 1

        if not data["pageInfo"]["hasNextPage"]:
            break

        cursor = data["pageInfo"]["endCursor"]

    return year_counts


def get_pr_reviews(pr_number):
    url = f"{base_url}/pulls/{pr_number}/reviews"
    response = requests.get(url, headers=headers)
    reviews = response.json()
    # Ensure reviews is a list
    if isinstance(reviews, list):
        return reviews

    print(f"Unexpected response format for PR #{pr_number} reviews: {reviews}")
    return []


def is_pr_approved(reviews):
    return any(review["state"] == "APPROVED" for review in reviews)


# pylint: disable=too-many-locals
def get_pr_commits(pr_number, headers=None):
    """
    Get all commits for a given PR number.

    Args:
        pr_number: The PR number to get commits for
        headers: Optional request headers. If None, will use default GitHub API headers
    """
    if headers is None:
        headers = setup_github_api()["headers"]

    url = f"{base_url}/pulls/{pr_number}/commits"
    commits = []
    while url:
        response = requests.get(url, headers=headers)
        commits.extend(response.json())
        url = response.links.get("next", {}).get("url")
    return commits


# pylint: disable=too-many-locals
def get_check_runs(pr_number):
    commits = get_pr_commits(pr_number)
    all_check_runs = []
    for commit in commits:
        url = f"{base_url}/commits/{commit['sha']}/check-runs"
        while url:
            response = requests.get(url, headers=headers)
            if response.status_code != 200:
                print(f"Failed  to fetch / Noneexistent check runs for commit {commit['sha']}: {response.status_code}")
                break
            data = response.json()
            if "check_runs" not in data:
                print(f"No check runs found for commit {commit['sha']}")
            else:
                verbose_print(f"Found {len(data['check_runs'])} check runs for commit {commit['sha']}")
            all_check_runs.extend(data.get("check_runs", []))
            url = response.links.get("next", {}).get("url")
    return all_check_runs


# pylint: disable=too-many-locals
def print_metrics(pr_metrics):
    # First, organize PRs by year
    yearly_prs = defaultdict(list)
    for month, prs in pr_metrics.items():
        year = month.split("-")[0]
        yearly_prs[year].extend(prs)

    # Print statistics for each year
    for year, prs in sorted(yearly_prs.items()):
        print(f"\nOverall Statistics for {year}:")

        # Calculate yearly metrics
        merge_times = [pr["merge_time"] for pr in prs]
        check_times = [pr["total_check_time"] for pr in prs]

        # Convert to appropriate units
        merge_times_hours = [t / 3600 for t in merge_times]
        check_times_minutes = [t / 60 for t in check_times]

        # Calculate metrics for the year
        total_prs = len(prs)
        median_merge_time_hours = statistics.median(merge_times_hours)
        median_check_time_minutes = statistics.median(check_times_minutes)
        avg_check_time_minutes = statistics.mean(check_times_minutes)
        avg_merge_time_hours = statistics.mean(merge_times_hours)

        # Calculate ratios
        avg_check_merge_ratio = (avg_check_time_minutes / (avg_merge_time_hours * 60)) * 100
        median_check_merge_ratio = (median_check_time_minutes / (median_merge_time_hours * 60)) * 100

        # Print yearly statistics
        print(f"Total PRs: {total_prs}")
        print(f"Median PR Merge Time (hours): {median_merge_time_hours:.2f}")
        print(f"Median CI Build Time (minutes): {median_check_time_minutes:.2f}")
        print(f"Average CI Build Time (minutes): {avg_check_time_minutes:.2f}")
        print(f"Average PR Merge Time (hours): {avg_merge_time_hours:.2f}")
        print(f"Average Check Time / Average Merge Time Ratio (%): {avg_check_merge_ratio:.2f}")
        print(f"Median Check Time / Median Merge Time Ratio (%): {median_check_merge_ratio:.2f}")

        # Print monthly breakdown for this year
        print(f"\nMonthly Breakdown for {year}:")
        print(
            "Month, PRs, Median Merge (hrs), Median Check (min), Avg Files Changed, Avg Review Time (hrs), Check Success Rate (%)"
        )

        # Filter and sort months for this year
        year_months = {month: prs for month, prs in pr_metrics.items() if month.startswith(year)}
        for month, month_prs in sorted(year_months.items()):
            merge_times = [pr["merge_time"] for pr in month_prs]
            check_times = [pr["total_check_time"] for pr in month_prs]
            files_changed = [pr["code_changes"]["changed_files"] for pr in month_prs]
            review_times = [
                pr["reviews"]["time_to_first_review"] for pr in month_prs if pr["reviews"]["time_to_first_review"]
            ]

            total_checks = sum(pr["checks"]["successful"] + pr["checks"]["failed"] for pr in month_prs)
            successful_checks = sum(pr["checks"]["successful"] for pr in month_prs)

            median_merge_time_hours = statistics.median(merge_times) / 3600
            median_check_time_minutes = statistics.median(check_times) / 60
            avg_files_changed = statistics.mean(files_changed)
            avg_review_time_hours = statistics.mean(review_times) / 3600 if review_times else 0
            check_success_rate = (successful_checks / total_checks * 100) if total_checks > 0 else 0

            print(
                f"{month}, {len(month_prs)}, {median_merge_time_hours:.2f}, {median_check_time_minutes:.2f}, "
                f"{avg_files_changed:.1f}, {avg_review_time_hours:.2f}, {check_success_rate:.1f}"
            )


# following UTC time format although it's possible that the CI was running in a different timezone
def main():
    parser = get_common_parser()
    args = parser.parse_args()

    if args.force_fresh and args.load_from_file:
        print("Error: Cannot use both --force-fresh and --load-from-file together")
        parser.print_help()
        return

    try:
        print("Retrieving yearly stats for approved and merged PRs...")
        print("Retrieving yearly stats for merged PRs...")
        start_year = 2024
        end_year = 2025
        yearly_counts = get_merged_prs_for_years(start_year, end_year)
        for year, count in yearly_counts.items():
            print(f"Total merged PRs for {year}: {count}")

        print("\nProceeding with regular PR metrics...")

        args = parse_common_arguments()
        start_date = f"{start_year}-01-01T00:00:00Z"  # Updated to match your previous output

        if args.load_from_file:
            prs = load_from_file(args.load_from_file)
            if prs is None:
                return
        else:
            try:
                prs = get_pull_requests(start_date)
                if args.save_to_file:
                    save_to_file(prs, args.save_to_file)
            except Exception as e:
                print(f"Failed to fetch PRs: {e}")
                return

        if not prs:
            print("No PRs found to analyze")
            return

        metrics = calculate_metrics(prs)
        print_metrics(metrics)

    except Exception as e:
        print(f"Error in main: {str(e)}")
        traceback.print_exc()


if __name__ == "__main__":
    main()
