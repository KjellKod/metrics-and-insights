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
   - Median lines added
   - Median lines removed

4. pr_review_monthly_metrics.csv:
   Monthly review metrics showing:
   - Reviews participated
   - Reviews approved by person example: `is:pr is:merged merged:2025-01-01..2025-01-31 reviewed-by:<username>` in the github UI. 
   - Comments made


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
python3 fetch_pr_metrics_with_args.py --repos 'org/repo1,org2/repo2' \
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

def parse_datetime(date_str):
    """Convert GitHub date string to datetime object"""
    return datetime.fromisoformat(date_str.replace("Z", "+00:00"))

def calculate_hours_between(start_date_str, end_date_str):
    """Calculate hours between two datetime strings"""
    start = parse_datetime(start_date_str)
    end = parse_datetime(end_date_str)
    return round((end - start).total_seconds() / 3600, 2)

def get_pr_reviews(pr_number, repo, headers):
    """Fetch both reviews and review comments for a PR"""
    base_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    
    try:
        # Get all reviews (includes APPROVED, CHANGES_REQUESTED, COMMENTED)
        reviews_url = f"{base_url}/reviews"
        reviews_response = requests.get(reviews_url, headers=headers)
        reviews_response.raise_for_status()
        reviews = reviews_response.json()

        # Get all review comments
        comments_url = f"{base_url}/comments"
        comments_response = requests.get(comments_url, headers=headers)
        comments_response.raise_for_status()
        review_comments = comments_response.json()

        # Get issue comments (these can also be review-related)
        issue_comments_url = f"{base_url.replace('/pulls/', '/issues/')}/comments"
        issue_comments_response = requests.get(issue_comments_url, headers=headers)
        issue_comments_response.raise_for_status()
        issue_comments = issue_comments_response.json()

        return {
            'reviews': reviews,
            'review_comments': review_comments,
            'issue_comments': issue_comments
        }
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching reviews/comments for PR {pr_number} in {repo}: {str(e)}")
        return {'reviews': [], 'review_comments': [], 'issue_comments': []}

def process_pr_reviews(pr_number, repo, month, normalized_users, monthly_review_metrics, api_headers):
    """Process all review activity for a PR"""
    review_data = get_pr_reviews(pr_number, repo, api_headers)
    
    # Track unique reviewers for this PR
    pr_reviewers = set()
    
    # Process formal reviews
    for review in review_data['reviews']:
        reviewer = review['user']['login']
        if reviewer.lower() in normalized_users:
            pr_reviewers.add(reviewer)
            key = (month, reviewer)
            monthly_review_metrics.setdefault(key, {
                'reviews_participated': 0,
                'reviews_approved': 0,
                'comments_made': 0
            })
            
            if review['state'] == 'APPROVED':
                monthly_review_metrics[key]['reviews_approved'] += 1
            if review.get('body'):
                monthly_review_metrics[key]['comments_made'] += 1

    # Process review comments (inline comments)
    for comment in review_data['review_comments']:
        reviewer = comment['user']['login']
        if reviewer.lower() in normalized_users:
            pr_reviewers.add(reviewer)
            key = (month, reviewer)
            monthly_review_metrics.setdefault(key, {
                'reviews_participated': 0,
                'reviews_approved': 0,
                'comments_made': 0
            })
            monthly_review_metrics[key]['comments_made'] += 1

    # Process issue comments
    for comment in review_data['issue_comments']:
        reviewer = comment['user']['login']
        if reviewer.lower() in normalized_users:
            pr_reviewers.add(reviewer)
            key = (month, reviewer)
            monthly_review_metrics.setdefault(key, {
                'reviews_participated': 0,
                'reviews_approved': 0,
                'comments_made': 0
            })
            monthly_review_metrics[key]['comments_made'] += 1

    # Count unique PR participation
    for reviewer in pr_reviewers:
        key = (month, reviewer)
        monthly_review_metrics[key]['reviews_participated'] += 1

    return monthly_review_metrics

def write_monthly_volume_metrics(monthly_author_metrics, filename="pr_volume_monthly_metrics.csv"):
    """
    Write monthly volume metrics by author to CSV file.
    
    Args:
        monthly_author_metrics (dict): Dictionary containing metrics data
        filename (str): Output filename for the CSV
    """
    volume_metrics_path = Path(filename)
    try:
        with open(filename, mode='w', newline='', encoding='utf-8') as metrics_csv:
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
        return volume_metrics_path
    except IOError as e:
        logger.error(f"Error writing to monthly volume metrics file {filename}: {str(e)}")
        return None

def write_monthly_merge_times(sorted_pr_data, filename="pr_merge_times_monthly.csv"):
    """
    Write monthly merge time metrics to CSV file.
    
    Args:
        sorted_pr_data (list): List of PR data entries
        filename (str): Output filename for the CSV
    """
    # Calculate median merge times per month
    median_merge_times = {}
    for pr_entry in sorted_pr_data:
        date = pr_entry['row'][0]
        month = date.strftime("%Y-%m")
        hours_to_merge = pr_entry['row'][7]  # Hours to merge is the last column
        
        if month not in median_merge_times:
            median_merge_times[month] = []
        median_merge_times[month].append(hours_to_merge)

    # Write median merge times to CSV
    merge_time_path = Path(filename)
    try:
        with open(filename, mode='w', newline='', encoding='utf-8') as merge_csv:
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
        logger.error(f"Error writing to monthly merge time file {filename}: {str(e)}")

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
                    
                    # Instead of just searching for authored PRs, also search for reviewed PRs
                    for search_type in ['author', 'reviewed-by']:
                        SEARCH_URL = f"{GITHUB_API}/search/issues"
                        query = f"repo:{repo} is:pr is:merged {search_type}:{author} merged:{START_DATE}..{END_DATE}"
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
                                merged_at = parse_datetime(pr_data["merged_at"])
                                month = merged_at.strftime("%Y-%m")
                                
                                # Process reviews for this PR
                                monthly_review_metrics = process_pr_reviews(
                                    pr_number,
                                    repo,
                                    month,
                                    normalized_users,
                                    monthly_review_metrics,
                                    API_HEADERS
                                )
                            
                        except requests.exceptions.RequestException as e:
                            logger.error(f"Error fetching data for {repo} and {author}: {str(e)}")
                            continue

            # Sort all PR data by date and write to file
            sorted_pr_data = sorted(all_pr_data, key=lambda x: x['date'])
            for pr_entry in sorted_pr_data:
                print_and_write_row(pr_entry['row'], writer)

            # Initialize data structures for metrics
            monthly_author_metrics = {}
            monthly_metrics = {}
            
            # Process all PR data for metrics
            for pr_entry in sorted_pr_data:
                date = pr_entry['row'][0]
                author = pr_entry['row'][1]
                month = date.strftime("%Y-%m")
                
                # Initialize metrics for this month/author if not exists
                key = (month, author)
                if key not in monthly_author_metrics:
                    monthly_author_metrics[key] = {
                        'pr_count': 0,
                        'hours_to_merge': [],
                        'lines_added': [],
                        'lines_removed': []
                    }
                
                # Update metrics
                monthly_author_metrics[key]['pr_count'] += 1
                monthly_author_metrics[key]['hours_to_merge'].append(pr_entry['row'][7])
                monthly_author_metrics[key]['lines_added'].append(pr_entry['row'][4])
                monthly_author_metrics[key]['lines_removed'].append(pr_entry['row'][5])

                # Initialize and update monthly metrics
                if month not in monthly_metrics:
                    monthly_metrics[month] = {
                        'hours_to_merge': [],
                        'lines_added': [],
                        'lines_removed': [],
                        'total_changes': []
                    }
                
                monthly_metrics[month]['hours_to_merge'].append(pr_entry['row'][7])
                monthly_metrics[month]['lines_added'].append(pr_entry['row'][4])
                monthly_metrics[month]['lines_removed'].append(pr_entry['row'][5])
                monthly_metrics[month]['total_changes'].append(pr_entry['row'][4] + pr_entry['row'][5])

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
            write_monthly_merge_times(sorted_pr_data, filename="pr_merge_times_monthly.csv")

            # Create monthly metrics by author and capture the path
            volume_metrics_path = write_monthly_volume_metrics(monthly_author_metrics, filename="pr_volume_monthly_metrics.csv")

            # Write review metrics
            review_metrics_file = "pr_review_monthly_metrics.csv"
            review_metrics_path = Path(review_metrics_file)
            try:
                with open(review_metrics_file, mode='w', newline='', encoding='utf-8') as metrics_csv:
                    writer = csv.writer(metrics_csv)
                    
                    # First format: Detailed rows
                    writer.writerow([
                        "Month",
                        "Reviewer",
                        "Reviews Participated",
                        "Reviews Approved",
                        "Comments Made"
                    ])
                    
                    for (month, reviewer) in sorted(monthly_review_metrics.keys()):
                        metrics = monthly_review_metrics[(month, reviewer)]
                        row = [
                            month,
                            reviewer,
                            metrics['reviews_participated'],
                            metrics['reviews_approved'],
                            metrics['comments_made']
                        ]
                        writer.writerow(row)

                    # Add blank lines between formats
                    writer.writerow([])
                    writer.writerow([])

                    # Get unique months and reviewers
                    months = sorted(set(month for month, _ in monthly_review_metrics.keys()))
                    reviewers = sorted(set(reviewer for _, reviewer in monthly_review_metrics.keys()))

                    # Write pivoted format for each metric
                    metrics_to_pivot = [
                        ('Reviews Participated', 'reviews_participated'),
                        ('Reviews Approved', 'reviews_approved'),
                        ('Comments Made', 'comments_made')
                    ]

                    for title, metric_key in metrics_to_pivot:
                        # Write metric title
                        writer.writerow([title])
                        
                        # Write header with reviewers
                        writer.writerow(['Month'] + reviewers)
                        
                        # Write data rows
                        for month in months:
                            row = [month]
                            for reviewer in reviewers:
                                value = monthly_review_metrics.get((month, reviewer), {}).get(metric_key, 0)
                                row.append(value)
                            writer.writerow(row)
                        
                        # Add blank line between metrics
                        writer.writerow([])

                logger.info(f"✓ Successfully wrote review metrics to: {review_metrics_path.absolute()}")
            except IOError as e:
                logger.error(f"Error writing to review metrics file {review_metrics_file}: {str(e)}")

            try:
                logger.info("\nSummary:")
                
                # Log output files if they exist
                if output_path.exists():
                    logger.info(f"✓ Successfully wrote detailed data to: {output_path.absolute()}")
                
                metrics_file = Path("pr_monthly_metrics.csv")
                if metrics_file.exists():
                    logger.info(f"✓ Successfully wrote monthly metrics to: {metrics_file.absolute()}")
                
                volume_metrics_file = Path("pr_volume_monthly_metrics.csv")
                if volume_metrics_file.exists():
                    logger.info(f"✓ Successfully wrote monthly author metrics to: {volume_metrics_file.absolute()}")
                
                review_metrics_file = Path("pr_review_monthly_metrics.csv")
                if review_metrics_file.exists():
                    logger.info(f"✓ Successfully wrote review metrics to: {review_metrics_file.absolute()}")
                
                # Log summary statistics
                logger.info(f"✓ Total PRs processed: {total_prs}")
                logger.info(f"✓ Date range: {START_DATE} to {END_DATE}")
                logger.info(f"✓ Repositories processed: {len(REPOS)}")
                logger.info(f"✓ Users analyzed: {len(USERS)}")
                
            except Exception as e:
                logger.error(f"Error during summary logging: {str(e)}")
                sys.exit(1)

    except IOError as e:
        logger.error(f"Error writing to file {OUTPUT_FILE}: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
