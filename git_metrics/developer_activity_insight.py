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
   - Reviews approved by person
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

# Standard library imports
import argparse
import csv
import logging
import os
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Dict, List, Set, Tuple, Optional

# Third-party imports
import requests
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class PRData:
    """Data class to hold PR information"""

    date: datetime
    author: str
    repo: str
    number: int
    additions: int
    deletions: int
    changed_files: int
    hours_to_merge: float


@dataclass
class MonthlyMetrics:
    """Data class to hold monthly metrics for an author"""

    month: str
    hours_to_merge: List[float]
    lines_added: List[int]
    lines_removed: List[int]
    total_changes: List[int]
    reviews_participated: int = 0
    review_response_times: List[float] = field(default_factory=list)


@dataclass
class ReviewMetrics:
    """Data class to hold review metrics for an author"""

    reviews_participated: int = 0
    reviews_approved: int = 0
    comments_made: int = 0
    review_response_times: List[float] = field(default_factory=list)


class GitHubAPI:
    """Handles all GitHub API interactions"""

    def __init__(self, token: str):
        self.base_url = "https://api.github.com"
        self.headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}

    def get_prs(self, repo: str, author: str, start_date: str, end_date: str) -> List[dict]:
        """Fetch PRs for a given repo and author"""
        logger.info(f"Fetching PRs for {author} in {repo}")
        search_url = f"{self.base_url}/search/issues"
        query = f"repo:{repo} is:pr is:merged author:{author} merged:{start_date}..{end_date}"
        params = {"q": query, "per_page": 100, "page": 1}

        try:
            response = requests.get(search_url, headers=self.headers, params=params)
            response.raise_for_status()
            prs = response.json().get("items", [])
            logger.info(f"Found {len(prs)} PRs for {author} in {repo}")
            return prs
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching PRs for {author} in {repo}: {str(e)}")
            return []

    def get_pr_details(self, repo: str, pr_number: int) -> Optional[dict]:
        """Fetch detailed PR information"""
        logger.debug(f"Fetching details for PR #{pr_number} in {repo}")
        pr_url = f"{self.base_url}/repos/{repo}/pulls/{pr_number}"
        try:
            response = requests.get(pr_url, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching PR details for #{pr_number} in {repo}: {str(e)}")
            return None

    def get_pr_reviews(self, repo: str, pr_number: int) -> dict:
        """Fetch all review-related data for a PR"""
        logger.debug(f"Fetching reviews for PR #{pr_number} in {repo}")
        base_url = f"{self.base_url}/repos/{repo}/pulls/{pr_number}"

        try:
            reviews = requests.get(f"{base_url}/reviews", headers=self.headers).json()
            comments = requests.get(f"{base_url}/comments", headers=self.headers).json()
            issue_comments = requests.get(
                f"{base_url.replace('/pulls/', '/issues/')}/comments", headers=self.headers
            ).json()

            return {"reviews": reviews, "review_comments": comments, "issue_comments": issue_comments}
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching reviews for PR {pr_number} in {repo}: {str(e)}")
            return {"reviews": [], "review_comments": [], "issue_comments": []}


class MetricsWriter(ABC):
    """Abstract base class for metrics writers"""

    @abstractmethod
    def write(self, data: dict) -> None:
        pass


class PRMetricsWriter(MetricsWriter):
    """Handles writing PR metrics to CSV"""

    def __init__(self, output_file: str):
        self.output_file = output_file
        self.headers = [
            "Date",
            "Author",
            "Repository",
            "PR Number",
            "Lines added",
            "Lines removed",
            "Files Changed",
            "Hours to Merge",
        ]

    def _write_metric_section(
        self, writer: csv.writer, title: str, months: List[str], authors: List[str], get_value: callable
    ) -> None:
        """Helper method to write a metric section with consistent formatting"""
        writer.writerow([title])
        writer.writerow(["Month"] + authors)
        for month in months:
            row = [month]
            for author in authors:
                row.append(get_value(month, author))
            writer.writerow(row)
        writer.writerow([])

    def write(self, pr_data: List[PRData], monthly_metrics: dict, review_metrics: dict) -> None:
        with open(self.output_file, mode="w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)

            # Get unique months and authors
            months = sorted(set(pr.date.strftime("%Y-%m") for pr in pr_data))
            authors = sorted(set(pr.author for pr in pr_data))

            # Write all metric sections
            self._write_metric_section(
                writer,
                "PR Count",
                months,
                authors,
                lambda m, a: sum(1 for pr in pr_data if pr.date.strftime("%Y-%m") == m and pr.author == a),
            )

            self._write_metric_section(
                writer,
                "Reviews Participated",
                months,
                authors,
                lambda m, a: getattr(review_metrics.get((m, a)), "reviews_participated", 0),
            )

            self._write_metric_section(
                writer,
                "Reviews Approved",
                months,
                authors,
                lambda m, a: getattr(review_metrics.get((m, a)), "reviews_approved", 0),
            )

            self._write_metric_section(
                writer,
                "Comments Made",
                months,
                authors,
                lambda m, a: getattr(review_metrics.get((m, a)), "comments_made", 0),
            )

            self._write_metric_section(
                writer,
                "Median Hours to Merge",
                months,
                authors,
                lambda m, a: (
                    round(
                        median(
                            pr.hours_to_merge for pr in pr_data if pr.date.strftime("%Y-%m") == m and pr.author == a
                        ),
                        2,
                    )
                    if any(pr.date.strftime("%Y-%m") == m and pr.author == a for pr in pr_data)
                    else 0
                ),
            )

            self._write_metric_section(
                writer,
                "Median Lines Added",
                months,
                authors,
                lambda m, a: (
                    median(pr.additions for pr in pr_data if pr.date.strftime("%Y-%m") == m and pr.author == a)
                    if any(pr.date.strftime("%Y-%m") == m and pr.author == a for pr in pr_data)
                    else 0
                ),
            )

            self._write_metric_section(
                writer,
                "Median Lines Removed",
                months,
                authors,
                lambda m, a: (
                    median(pr.deletions for pr in pr_data if pr.date.strftime("%Y-%m") == m and pr.author == a)
                    if any(pr.date.strftime("%Y-%m") == m and pr.author == a for pr in pr_data)
                    else 0
                ),
            )

            self._write_metric_section(
                writer,
                "Median Files Changed",
                months,
                authors,
                lambda m, a: (
                    median(pr.changed_files for pr in pr_data if pr.date.strftime("%Y-%m") == m and pr.author == a)
                    if any(pr.date.strftime("%Y-%m") == m and pr.author == a for pr in pr_data)
                    else 0
                ),
            )

            self._write_metric_section(
                writer,
                "Average Hours to Merge",
                months,
                authors,
                lambda m, a: (
                    round(
                        sum(pr.hours_to_merge for pr in pr_data if pr.date.strftime("%Y-%m") == m and pr.author == a)
                        / sum(1 for pr in pr_data if pr.date.strftime("%Y-%m") == m and pr.author == a),
                        2,
                    )
                    if any(pr.date.strftime("%Y-%m") == m and pr.author == a for pr in pr_data)
                    else 0
                ),
            )

            self._write_metric_section(
                writer,
                "Average Review Response Time (hours)",
                months,
                authors,
                lambda m, a: (
                    round(
                        sum(getattr(review_metrics.get((m, a)), "review_response_times", []))
                        / len(getattr(review_metrics.get((m, a)), "review_response_times", [])),
                        2,
                    )
                    if getattr(review_metrics.get((m, a)), "review_response_times", [])
                    else 0
                ),
            )

            # Add blank lines before detailed data
            writer.writerow([])
            writer.writerow([])

            # Detailed PR Data
            writer.writerow(["DETAILED PR DATA"])
            writer.writerow(self.headers)

            # Sort PRs by date (earliest first)
            sorted_prs = sorted(pr_data, key=lambda x: x.date)
            for pr in sorted_prs:
                writer.writerow(
                    [
                        pr.date.date(),
                        pr.author,
                        pr.repo,
                        pr.number,
                        pr.additions,
                        pr.deletions,
                        pr.changed_files,
                        pr.hours_to_merge,
                    ]
                )


class PRMetricsCollector:
    """Main class for collecting and processing PR metrics"""

    def __init__(self, token: str, users: List[str]):
        self.api = GitHubAPI(token)
        self.users = users
        self.metrics_writers = {"pr": PRMetricsWriter("pr_metrics.csv")}
        # Cache for PR creation times
        self.pr_creation_times = {}

    def _get_pr_creation_time(self, repo: str, pr_number: int) -> Optional[datetime]:
        """Get PR creation time from cache or API"""
        cache_key = f"{repo}/{pr_number}"
        if cache_key not in self.pr_creation_times:
            pr_details = self.api.get_pr_details(repo, pr_number)
            if pr_details and pr_details.get("created_at"):
                self.pr_creation_times[cache_key] = datetime.fromisoformat(
                    pr_details["created_at"].replace("Z", "+00:00")
                )
            else:
                return None
        return self.pr_creation_times[cache_key]

    def collect_pr_data(self, repos: List[str], users: List[str], start_date: str, end_date: str) -> List[PRData]:
        """Collect PR data for all repos and users"""
        logger.info(f"Starting PR data collection for {len(repos)} repos and {len(users)} users")
        pr_data = []
        total_prs = 0

        for repo in repos:
            for user in users:
                prs = self.api.get_prs(repo, user, start_date, end_date)
                total_prs += len(prs)
                logger.info(f"Processing {len(prs)} PRs for {user} in {repo}")

                for pr in prs:
                    details = self.api.get_pr_details(repo, pr["number"])
                    if details:
                        created_at = datetime.fromisoformat(details["created_at"].replace("Z", "+00:00"))
                        merged_at = datetime.fromisoformat(details["merged_at"].replace("Z", "+00:00"))
                        hours_to_merge = round((merged_at - created_at).total_seconds() / 3600, 2)

                        pr_data.append(
                            PRData(
                                date=merged_at,
                                author=details["user"]["login"],
                                repo=repo,
                                number=details["number"],
                                additions=details["additions"],
                                deletions=details["deletions"],
                                changed_files=details["changed_files"],
                                hours_to_merge=hours_to_merge,
                            )
                        )

        logger.info(f"Completed PR data collection. Total PRs processed: {total_prs}")
        return pr_data

    def process_metrics(self, pr_data: List[PRData]) -> Tuple[dict, dict]:
        """Process PR data into monthly and review metrics"""
        logger.info("Starting metrics processing")
        monthly_metrics = {}
        review_metrics = {}

        for pr in pr_data:
            month = pr.date.strftime("%Y-%m")
            key = (month, pr.author)

            # Initialize metrics for this month/author if not exists
            if key not in monthly_metrics:
                monthly_metrics[key] = MonthlyMetrics(
                    month=month, hours_to_merge=[], lines_added=[], lines_removed=[], total_changes=[]
                )

            # Update metrics
            monthly_metrics[key].hours_to_merge.append(pr.hours_to_merge)
            monthly_metrics[key].lines_added.append(pr.additions)
            monthly_metrics[key].lines_removed.append(pr.deletions)
            monthly_metrics[key].total_changes.append(pr.additions + pr.deletions)

            # Process review data
            logger.debug(f"Processing reviews for PR #{pr.number} in {pr.repo}")
            review_data = self.api.get_pr_reviews(pr.repo, pr.number)
            self._process_review_data(review_data, month, review_metrics, monthly_metrics[key])

        logger.info("Completed metrics processing")
        return monthly_metrics, review_metrics

    def _process_review_data(
        self, review_data: dict, month: str, review_metrics: dict, author_metrics: MonthlyMetrics
    ) -> None:
        """Process review data and update metrics"""
        # Process formal reviews
        for review in review_data["reviews"]:
            reviewer = review["user"]["login"]
            # Only process reviews from specified users
            if reviewer.lower() not in [u.lower() for u in self.users]:
                continue

            key = (month, reviewer)

            if key not in review_metrics:
                review_metrics[key] = ReviewMetrics()

            # Count the review participation
            review_metrics[key].reviews_participated += 1

            # Count approvals
            if review["state"] == "APPROVED":
                review_metrics[key].reviews_approved += 1

            # Count review body comments
            if review.get("body"):
                review_metrics[key].comments_made += 1

            # Update author metrics
            author_metrics.reviews_participated += 1

            # Calculate review response time
            if review.get("submitted_at"):
                review_time = datetime.fromisoformat(review["submitted_at"].replace("Z", "+00:00"))
                # Extract repo and PR number from the URL
                pr_url = review["pull_request_url"]
                repo = "/".join(pr_url.split("/")[-4:-2])  # Get org/repo from URL
                pr_number = int(pr_url.split("/")[-1])

                pr_created = self._get_pr_creation_time(repo, pr_number)
                if pr_created:
                    response_time = (review_time - pr_created).total_seconds() / 3600
                    review_metrics[key].review_response_times.append(response_time)

        # Process review comments (inline comments)
        for comment in review_data["review_comments"]:
            reviewer = comment["user"]["login"]
            if reviewer.lower() not in [u.lower() for u in self.users]:
                continue

            key = (month, reviewer)
            if key not in review_metrics:
                review_metrics[key] = ReviewMetrics()

            # Count the comment
            review_metrics[key].comments_made += 1
            # Also count as review participation
            review_metrics[key].reviews_participated += 1

        # Process issue comments
        for comment in review_data["issue_comments"]:
            reviewer = comment["user"]["login"]
            if reviewer.lower() not in [u.lower() for u in self.users]:
                continue

            key = (month, reviewer)
            if key not in review_metrics:
                review_metrics[key] = ReviewMetrics()

            # Count the comment
            review_metrics[key].comments_made += 1
            # Also count as review participation
            review_metrics[key].reviews_participated += 1

    def generate_reports(self, pr_data: List[PRData], monthly_metrics: dict, review_metrics: dict) -> None:
        """Generate all metric reports"""
        self.metrics_writers["pr"].write(pr_data, monthly_metrics, review_metrics)


def main():
    # Load environment variables
    load_dotenv()

    # Parse arguments
    parser = argparse.ArgumentParser(description="Fetch PR metrics from GitHub.")
    parser.add_argument("--repos", required=True, help="Comma-separated list of GitHub repos")
    parser.add_argument("--users", required=True, help="Comma-separated list of GitHub usernames")
    parser.add_argument("--date_start", required=True, help="Start date in YYYY-MM-DD format")
    parser.add_argument("--date_end", required=True, help="End date in YYYY-MM-DD format")
    parser.add_argument("--output", default="pr_metrics.csv", help="Output CSV file name")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    # Set logging level based on debug flag
    if args.debug:
        logger.setLevel(logging.DEBUG)

    users = [u.strip() for u in args.users.split(",")]

    # Get GitHub token
    token = os.getenv("GITHUB_TOKEN_READONLY_WEB")
    if not token:
        raise EnvironmentError("GITHUB_TOKEN_READONLY_WEB environment variable is not set.")

    logger.info("Starting PR metrics collection")
    logger.info(f"Repos: {args.repos}")
    logger.info(f"Users: {args.users}")
    logger.info(f"Date range: {args.date_start} to {args.date_end}")

    # Initialize collector and process data
    collector = PRMetricsCollector(token, users)

    # Collect PR data
    pr_data = collector.collect_pr_data(
        [r.strip() for r in args.repos.split(",")], users, args.date_start, args.date_end
    )

    # Process metrics
    monthly_metrics, review_metrics = collector.process_metrics(pr_data)

    # Generate reports
    logger.info("Generating reports")
    collector.generate_reports(pr_data, monthly_metrics, review_metrics)

    # Log summary
    logger.info("\nSummary:")
    logger.info(f"✓ Total PRs processed: {len(pr_data)}")
    logger.info(f"✓ Date range: {args.date_start} to {args.date_end}")
    logger.info(f"✓ Repositories processed: {len(args.repos.split(','))}")
    logger.info(f"✓ Users analyzed: {len(users)}")


if __name__ == "__main__":
    main()
