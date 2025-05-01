#!/usr/bin/env python3

"""
GitHub Pull Request Metrics Generator
===================================

This script generates detailed PR metrics reports for specified GitHub repositories and users.
It creates three CSV files containing different levels of PR analytics.

Output Files
-----------
1. pr_metrics.csv:
   Detailed data for each PR including date, author, repository, PR number, lines changed,
   and time to merge.

2. pr_monthly_metrics.csv:
   Monthly aggregated metrics showing PR counts and median values for:
   - Hours to merge
   - Lines added/removed
   - Total changes

3. pr_volume_monthly_metrics.csv:
   Monthly metrics broken down by author, including:
   - PR count per author
   - Median hours to merge
   - Median lines added/removed

Requirements
-----------
- Python 3.6+
- GitHub Personal Access Token with repo access
- Required Python packages: requests, python-dotenv

Environment Variables
-------------------
GITHUB_TOKEN_READONLY_WEB: GitHub Personal Access Token

Usage
-----
python3 fetch_pr_metrics_with_args.py --repos 'org/repo1,org/repo2' \
                                    --users 'user1,user2' \
                                    --date_start '2023-01-01' \
                                    --date_end '2023-12-31' \
                                    [--output pr_metrics.csv]

Arguments
---------
--repos:       Comma-separated list of GitHub repos (e.g., 'org1/repo1,org2/repo2')
--users:       Comma-separated list of GitHub usernames
--date_start:  Start date in YYYY-MM-DD format
--date_end:    End date in YYYY-MM-DD format
--output:      Output CSV file name (default: pr_metrics.csv)

Example
-------
python3 fetch_pr_metrics_with_args.py \
    --repos 'facebook/react,facebook/jest' \
    --users 'user1,user2' \
    --date_start '2023-01-01' \
    --date_end '2023-12-31'
"""

import os
import sys
import argparse
import requests
from datetime import datetime
import csv
from dotenv import load_dotenv
import logging
from pathlib import Path
from statistics import median

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_pr_reviews(pr_number, repo, headers):
    """Fetch review data for a PR"""
    reviews_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews"
    try:
        response = requests.get(reviews_url, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching reviews for PR {reviews_url}: {str(e)}")
        return []

def main():
    # Load environment variables
    load_dotenv()

    # Argument parser setup
    parser = argparse.ArgumentParser(description="Fetch PR metrics from GitHub.")
    parser.add_argument("--repos", required=True, help="Comma-separated list of GitHub repos (e.g., 'org1/repo1,org2/repo2')")
    parser.add_argument("--users", required=True, help="Comma-separated list of GitHub usernames")
    parser.add_argument("--date_start", required=True, help="Start date in YYYY-MM-DD format")
    parser.add_argument("--date_end", required=True, help="End date in YYYY-MM-DD format")
    parser.add_argument("--output", default="pr_metrics.csv", help="Output CSV file name (default: pr_metrics.csv)")

    args = parser.parse_args()
    REPOS = [r.strip() for r in args.repos.split(",")]
    USERS = [u.strip() for u in args.users.split(",")]
    normalized_users = [u.strip().lower() for u in USERS]
    START_DATE = args.date_start
    END_DATE = args.date_end
    OUTPUT_FILE = args.output

    # Read GitHub token from environment
    TOKEN = os.getenv("GITHUB_TOKEN_READONLY_WEB")
    if not TOKEN:
        raise EnvironmentError("GITHUB_TOKEN_READONLY_WEB environment variable is not set.")

    # API configuration
    GITHUB_API = "https://api.github.com"
    API_HEADERS = {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    # Output column headers
    OUTPUT_HEADERS = [
        "Date",
        "Author",
        "Repository",
        "PR Number",
        "Lines added",
        "Lines removed",
        "Files Changed",
        "Hours to Merge"
    ]

    def print_and_write_row(row, csv_writer):
        print(",".join(str(x) for x in row))
        csv_writer.writerow(row)

    # Create output directory if it doesn't exist
    output_path = Path(OUTPUT_FILE)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Add review metrics tracking
    monthly_review_metrics = {}

    # Process and write data
    try:
        with open(OUTPUT_FILE, mode='w', newline='', encoding='utf-8') as csv_file:
            writer = csv.writer(csv_file)
            print_and_write_row(OUTPUT_HEADERS, writer)
            
            total_prs = 0
            all_pr_data = []  # List to store all PR data before sorting
            
            for repo in REPOS:
                logger.info(f"Processing repository: {repo}")
                for author in USERS:
                    logger.info(f"Fetching PRs for {author} in {repo}")
                    
                    SEARCH_URL = f"{GITHUB_API}/search/issues"
                    query = f"repo:{repo} is:pr is:merged author:{author} merged:{START_DATE}..{END_DATE}"
                    params = {
                        "q": query,
                        "per_page": 100,
                        "page": 1
                    }

                    try:
                        response = requests.get(SEARCH_URL, headers=API_HEADERS, params=params)
                        response.raise_for_status()
                        data = response.json()
                        
                        pr_count = data.get("total_count", 0)
                        total_prs += pr_count
                        logger.info(f"Found {pr_count} PRs for {author} in {repo}")

                        for pr in data.get("items", []):
                            pr_url = pr["pull_request"]["url"]
                            pr_response = requests.get(pr_url, headers=API_HEADERS)
                            pr_response.raise_for_status()
                            pr_data = pr_response.json()

                            created_at = datetime.fromisoformat(pr_data["created_at"].replace("Z", "+00:00"))
                            merged_at = datetime.fromisoformat(pr_data["merged_at"].replace("Z", "+00:00"))
                            hours_to_merge = round((merged_at - created_at).total_seconds() / 3600, 2)

                            # Store data in list instead of writing immediately
                            all_pr_data.append({
                                'date': merged_at.date(),
                                'row': [
                                    merged_at.date(),
                                    pr_data["user"]["login"],
                                    repo,
                                    pr_data["number"],
                                    pr_data["additions"],
                                    pr_data["deletions"],
                                    pr_data["changed_files"],
                                    hours_to_merge
                                ]
                            })

                            # Fetch review data
                            pr_number = pr_data["number"]
                            reviews = get_pr_reviews(pr_number, repo, API_HEADERS)
                            
                            # Process reviews
                            for review in reviews:
                                reviewer = review['user']['login']
                                review_state = review['state']
                                month = merged_at.strftime("%Y-%m")
                                
                                if reviewer.lower() in normalized_users:
                                    key = (month, reviewer)
                                    if key not in monthly_review_metrics:
                                        monthly_review_metrics[key] = {
                                            'reviews_participated': 0,
                                            'reviews_approved': 0,
                                            'comments_made': 0
                                        }
                                    
                                    monthly_review_metrics[key]['reviews_participated'] += 1
                                    if review_state == 'APPROVED':
                                        monthly_review_metrics[key]['reviews_approved'] += 1
                                    if review.get('body'):  # Count comments in reviews
                                        monthly_review_metrics[key]['comments_made'] += 1

                    except requests.exceptions.RequestException as e:
                        logger.error(f"Error fetching data for {repo} and {author}: {str(e)}")
                        continue

            # Sort all PR data by date and write to file
            sorted_pr_data = sorted(all_pr_data, key=lambda x: x['date'])
            for pr_entry in sorted_pr_data:
                print_and_write_row(pr_entry['row'], writer)

            # Create monthly PR volume aggregation
            monthly_data = {}
            discovered_authors = set()
            
            # Normalize input users to lowercase for comparison
            normalized_users = [u.strip().lower() for u in args.users.split(",")]
            
            # First pass: collect all authors and initialize monthly data
            for pr_entry in sorted_pr_data:
                date = pr_entry['row'][0]  # Date
                author = pr_entry['row'][1]  # Author
                month = date.strftime("%Y-%m")  # Convert to YYYY-MM format
                
                # Store original case for display but compare in lowercase
                if author.lower() in normalized_users:
                    discovered_authors.add(author)  # Keep original case
                
                if month not in monthly_data:
                    monthly_data[month] = {}

            # Initialize counts for all authors in all months
            all_authors = sorted(discovered_authors)  # Use discovered authors with original case
            for month in monthly_data:
                monthly_data[month] = {author: 0 for author in all_authors}

            # Second pass: count PRs
            for pr_entry in sorted_pr_data:
                date = pr_entry['row'][0]
                author = pr_entry['row'][1]
                month = date.strftime("%Y-%m")
                if author in monthly_data[month]:  # Only count if author is in our list
                    monthly_data[month][author] += 1

            # Optional: Add warning about case mismatches
            found_authors_lower = {author.lower() for author in discovered_authors}
            if found_authors_lower != set(normalized_users):
                logger.warning("Note: Some usernames might have different cases than provided in --users argument")
                logger.warning(f"Provided usernames: {args.users}")
                logger.warning(f"Found usernames: {', '.join(sorted(discovered_authors))}")

            # Write monthly volume data to separate CSV
            volume_file = "pr_volume_monthly.csv"
            volume_path = Path(volume_file)
            try:
                with open(volume_file, mode='w', newline='', encoding='utf-8') as volume_csv:
                    volume_writer = csv.writer(volume_csv)
                    
                    # Write headers
                    headers = ["Month"] + all_authors
                    volume_writer.writerow(headers)
                    
                    # Sort by month and write data
                    for month in sorted(monthly_data.keys()):
                        row = [month] + [monthly_data[month][author] for author in all_authors]
                        volume_writer.writerow(row)
                
                logger.info(f"✓ Successfully wrote monthly PR volume data to: {volume_path.absolute()}")
            except IOError as e:
                logger.error(f"Error writing to monthly PR volume file {volume_file}: {str(e)}")

            # Create monthly median time to merge data
            median_merge_times = {}
            for pr_entry in sorted_pr_data:
                date = pr_entry['row'][0]
                month = date.strftime("%Y-%m")
                hours_to_merge = pr_entry['row'][7]  # Hours to merge is the last column
                
                if month not in median_merge_times:
                    median_merge_times[month] = []
                median_merge_times[month].append(hours_to_merge)

            # Write median merge times to CSV
            merge_time_file = "pr_merge_times_monthly.csv"
            merge_time_path = Path(merge_time_file)
            try:
                with open(merge_time_file, mode='w', newline='', encoding='utf-8') as merge_csv:
                    merge_writer = csv.writer(merge_csv)
                    
                    # Write headers
                    merge_writer.writerow(["Month", "Median Hours to Merge", "Number of PRs"])
                    
                    # Calculate and write median for each month
                    for month in sorted(median_merge_times.keys()):
                        monthly_hours = median_merge_times[month]
                        monthly_median = round(median(monthly_hours), 2)
                        monthly_pr_count = len(monthly_hours)
                        merge_writer.writerow([month, monthly_median, monthly_pr_count])
                
                logger.info(f"✓ Successfully wrote monthly merge time data to: {merge_time_path.absolute()}")
            except IOError as e:
                logger.error(f"Error writing to monthly merge time file {merge_time_file}: {str(e)}")

            # Create monthly metrics by author
            monthly_author_metrics = {}
            # Create overall monthly metrics
            monthly_metrics = {}
            
            for pr_entry in sorted_pr_data:
                date = pr_entry['row'][0]
                author = pr_entry['row'][1]
                month = date.strftime("%Y-%m")
                
                # For author-specific metrics
                key = (month, author)
                metrics = {
                    'hours_to_merge': pr_entry['row'][7],
                    'lines_added': pr_entry['row'][4],
                    'lines_removed': pr_entry['row'][5],
                    'total_changes': pr_entry['row'][4] + pr_entry['row'][5]
                }
                
                # Author metrics
                if key not in monthly_author_metrics:
                    monthly_author_metrics[key] = {
                        'pr_count': 0,
                        'hours_to_merge': [],
                        'lines_added': [],
                        'lines_removed': []
                    }
                
                monthly_author_metrics[key]['pr_count'] += 1
                for metric_name, value in metrics.items():
                    if metric_name != 'total_changes':  # Don't store total_changes in author metrics
                        monthly_author_metrics[key][metric_name].append(value)

                # Overall monthly metrics
                if month not in monthly_metrics:
                    monthly_metrics[month] = {
                        'hours_to_merge': [],
                        'lines_added': [],
                        'lines_removed': [],
                        'total_changes': []
                    }
                
                for metric_name, value in metrics.items():
                    monthly_metrics[month][metric_name].append(value)

            # Write overall monthly metrics
            metrics_file = "pr_monthly_metrics.csv"
            metrics_path = Path(metrics_file)
            try:
                with open(metrics_file, mode='w', newline='', encoding='utf-8') as metrics_csv:
                    metrics_writer = csv.writer(metrics_csv)
                    metrics_writer.writerow([
                        "Month",
                        "PR Count",
                        "Median Hours to Merge",
                        "Median Lines Added",
                        "Median Lines Removed",
                        "Median Total Changes"
                    ])
                    
                    for month in sorted(monthly_metrics.keys()):
                        metrics = monthly_metrics[month]
                        row = [
                            month,
                            len(metrics['hours_to_merge']),
                            round(median(metrics['hours_to_merge']), 2),
                            round(median(metrics['lines_added']), 2),
                            round(median(metrics['lines_removed']), 2),
                            round(median(metrics['total_changes']), 2)
                        ]
                        metrics_writer.writerow(row)
                
                logger.info(f"✓ Successfully wrote monthly metrics data to: {metrics_path.absolute()}")
            except IOError as e:
                logger.error(f"Error writing to monthly metrics file {metrics_file}: {str(e)}")

            # Write monthly metrics by author
            volume_metrics_file = "pr_volume_monthly_metrics.csv"
            volume_metrics_path = Path(volume_metrics_file)
            try:
                with open(volume_metrics_file, mode='w', newline='', encoding='utf-8') as metrics_csv:
                    metrics_writer = csv.writer(metrics_csv)
                    metrics_writer.writerow([
                        "Month",
                        "Author",
                        "PR Count",
                        "Median Hours to Merge",
                        "Median Lines Added",
                        "Median Lines Removed"
                    ])
                    
                    for (month, author) in sorted(monthly_author_metrics.keys()):
                        metrics = monthly_author_metrics[(month, author)]
                        row = [
                            month,
                            author,
                            metrics['pr_count'],
                            round(median(metrics['hours_to_merge']), 2),
                            round(median(metrics['lines_added']), 2),
                            round(median(metrics['lines_removed']), 2)
                        ]
                        metrics_writer.writerow(row)
                
                logger.info(f"✓ Successfully wrote monthly volume metrics by author to: {volume_metrics_path.absolute()}")
            except IOError as e:
                logger.error(f"Error writing to monthly volume metrics file {volume_metrics_file}: {str(e)}")

            # Write review metrics
            review_metrics_file = "pr_review_monthly_metrics.csv"
            review_metrics_path = Path(review_metrics_file)
            try:
                with open(review_metrics_file, mode='w', newline='', encoding='utf-8') as metrics_csv:
                    metrics_writer = csv.writer(metrics_csv)
                    metrics_writer.writerow([
                        "Month",
                        "Reviewer",
                        "Reviews Participated",
                        "Reviews Approved",
                        "Comments Made"
                    ])
                    
                    if monthly_review_metrics:
                        for (month, reviewer) in sorted(monthly_review_metrics.keys()):
                            metrics = monthly_review_metrics[(month, reviewer)]
                            row = [
                                month,
                                reviewer,
                                metrics['reviews_participated'],
                                metrics['reviews_approved'],
                                metrics['comments_made']
                            ]
                            metrics_writer.writerow(row)
                        logger.info(f"✓ Successfully wrote monthly review metrics to: {review_metrics_path.absolute()}")
                    else:
                        logger.warning("No review data found to write to file")
            finally:
                # Close the file if it was opened
                metrics_csv.close()
                logger.info(f"✓ Successfully closed review metrics file: {review_metrics_path.absolute()}")
            logger.info(f"\nSummary:")
            logger.info(f"✓ Successfully wrote detailed data to: {output_path.absolute()}")
            logger.info(f"✓ Successfully wrote monthly metrics to: {metrics_path.absolute()}")
            logger.info(f"✓ Successfully wrote monthly author metrics to: {volume_metrics_path.absolute()}")
            logger.info(f"✓ Successfully wrote review metrics to: {review_metrics_path.absolute()}")
            logger.info(f"✓ Total PRs processed: {total_prs}")
            logger.info(f"✓ Date range: {START_DATE} to {END_DATE}")
            logger.info(f"✓ Repositories processed: {len(REPOS)}")
            logger.info(f"✓ Users analyzed: {len(USERS)}")

    except IOError as e:
        logger.error(f"Error writing to file {OUTPUT_FILE}: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
