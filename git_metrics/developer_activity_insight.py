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
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Dict, List, Set, Tuple, Optional

# Third-party imports
import requests
from dotenv import load_dotenv
import pytz

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Utils:
    """Utility functions shared across classes"""

    @staticmethod
    def normalize_username(username: str) -> str:
        """Normalize username to lowercase for consistent comparison"""
        return username.lower() if username else ""


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
    # Add PR details for debugging
    pr_details: List[Tuple[str, int, float]] = field(default_factory=list)  # (repo, number, hours)


@dataclass
class ReviewMetrics:
    """Data class to hold review metrics for an author"""

    reviews_participated: int = 0
    reviews_approved: int = 0
    comments_made: int = 0
    review_response_times: List[float] = field(default_factory=list)
    author_wait_times: List[float] = field(default_factory=list)  # Time authors wait for reviews


class GitHubAPI:
    """Handles all GitHub API interactions"""

    def __init__(self, token: str, users: List[str]):
        self.base_url = "https://api.github.com"
        self.headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
        self.users = users

    def normalize_username(self, username: str) -> str:
        """Normalize username to lowercase for consistent comparison"""
        return Utils.normalize_username(username)

    def get_prs(self, repo: str, author: str, start_date: str, end_date: str) -> List[dict]:
        """Fetch PRs for a given repo and author"""
        logger.info(f"Fetching PRs for {author} in {repo}")
        search_url = f"{self.base_url}/search/issues"
        unique_prs = {}  # Use a dict to track unique PRs by number

        # Search for PRs authored by the user
        author_query = f"repo:{repo} is:pr is:merged author:{author} merged:{start_date}..{end_date}"
        try:
            response = requests.get(
                search_url, headers=self.headers, params={"q": author_query, "per_page": 100, "page": 1}, timeout=30
            )
            response.raise_for_status()
            author_prs = response.json().get("items", [])
            logger.info(f"Found {len(author_prs)} PRs authored by {author} in {repo}")
            for pr in author_prs:
                unique_prs[pr["number"]] = pr  # Store PR by number
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching authored PRs for {author} in {repo}: {str(e)}")

        # Search for PRs reviewed by the user
        reviewer_query = f"repo:{repo} is:pr is:merged review-requested:{author} merged:{start_date}..{end_date}"
        try:
            response = requests.get(
                search_url, headers=self.headers, params={"q": reviewer_query, "per_page": 100, "page": 1}, timeout=30
            )
            response.raise_for_status()
            reviewer_prs = response.json().get("items", [])
            logger.info(f"Found {len(reviewer_prs)} PRs reviewed by {author} in {repo}")
            for pr in reviewer_prs:
                unique_prs[pr["number"]] = pr
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching reviewed PRs for {author} in {repo}: {str(e)}")

        # Search for PRs where user commented
        commenter_query = f"repo:{repo} is:pr is:merged commenter:{author} merged:{start_date}..{end_date}"
        try:
            response = requests.get(
                search_url, headers=self.headers, params={"q": commenter_query, "per_page": 100, "page": 1}, timeout=30
            )
            response.raise_for_status()
            commenter_prs = response.json().get("items", [])
            logger.info(f"Found {len(commenter_prs)} PRs commented on by {author} in {repo}")
            for pr in commenter_prs:
                unique_prs[pr["number"]] = pr
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching commented PRs for {author} in {repo}: {str(e)}")

        # Convert dict values to list
        pr_list = list(unique_prs.values())
        logger.info(f"Total unique PRs found for {author} in {repo}: {len(pr_list)}")
        return pr_list

    def get_pr_details(self, repo: str, pr_number: int) -> Optional[dict]:
        """Fetch detailed PR information"""
        logger.debug(f"Fetching details for PR #{pr_number} in {repo}")
        pr_url = f"{self.base_url}/repos/{repo}/pulls/{pr_number}"
        try:
            response = requests.get(pr_url, headers=self.headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching PR details for #{pr_number} in {repo}: {str(e)}")
            return None

    def get_pr_reviews(self, repo: str, pr_number: int) -> dict:
        """Fetch all review-related data for a PR"""
        logger.debug(f"Fetching reviews for PR #{pr_number} in {repo}")
        base_url = f"{self.base_url}/repos/{repo}/pulls/{pr_number}"
        reviews = []
        comments = []
        issue_comments = []
        review_requests = []

        try:
            # Fetch all reviews and comments
            all_reviews = requests.get(f"{base_url}/reviews", headers=self.headers).json()
            all_comments = requests.get(f"{base_url}/comments", headers=self.headers).json()
            all_issue_comments = requests.get(
                f"{base_url.replace('/pulls/', '/issues/')}/comments", headers=self.headers
            ).json()

            # Fetch review request events
            events_url = f"{base_url.replace('/pulls/', '/issues/')}/events"
            all_events = requests.get(events_url, headers=self.headers).json()
            all_review_requests = [event for event in all_events if event.get("event") == "review_requested"]

            # Log all reviews and requests for debugging
            logger.debug(f"All reviews found for PR #{pr_number}:")
            for review in all_reviews:
                logger.debug(
                    f"  Review by {review['user']['login']} at {review.get('submitted_at')} - State: {review['state']}"
                )

            logger.debug(f"All review requests found for PR #{pr_number}:")
            for req in all_review_requests:
                reviewer = req.get("requested_reviewer", {}).get("login", "unknown")
                logger.debug(
                    f"  Review requested for {reviewer} at {req.get('created_at')} by {req.get('actor', {}).get('login')}"
                )

            return {
                "reviews": all_reviews,
                "review_comments": all_comments,
                "issue_comments": all_issue_comments,
                "review_requests": all_review_requests,
            }
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching reviews for PR {pr_number} in {repo}: {str(e)}")
            return {"reviews": [], "review_comments": [], "issue_comments": [], "review_requests": []}


class MetricsWriter(ABC):
    """Abstract base class for metrics writers"""

    @abstractmethod
    def write(self, data: dict) -> None:
        pass


class PRMetricsWriter(MetricsWriter):
    """Handles writing PR metrics to CSV"""

    def __init__(self, output_file: str, users: List[str]):
        self.output_file = output_file
        self.users = users
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

    def normalize_username(self, username: str) -> str:
        """Normalize username to lowercase for consistent comparison"""
        return Utils.normalize_username(username)

    def _matches_month_and_author(self, pr: PRData, month: str, author: str) -> bool:
        """Check if a PR matches both the given month and author"""
        return pr.date.strftime("%Y-%m") == month and self.normalize_username(pr.author) == self.normalize_username(
            author
        )

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

            # Get unique months
            months = sorted(set(pr.date.strftime("%Y-%m") for pr in pr_data))

            # Get authors from both PR data and review metrics, but only include specified users
            normalized_users = [self.normalize_username(u) for u in self.users]
            pr_authors = set(self.normalize_username(pr.author) for pr in pr_data)
            review_authors = set(self.normalize_username(author) for (_, author) in review_metrics.keys())

            # Debug output for authors
            logger.debug(f"\nAuthors found:")
            logger.debug(f"  From PRs: {pr_authors}")
            logger.debug(f"  From reviews: {review_authors}")
            logger.debug(f"  Specified users: {normalized_users}")

            # Get the original case version of usernames that have activity
            active_authors = []
            for user in self.users:
                normalized = self.normalize_username(user)
                if normalized in pr_authors or normalized in review_authors:
                    # Find the original case version from the PR data
                    for pr in pr_data:
                        if self.normalize_username(pr.author) == normalized:
                            active_authors.append(pr.author)
                            break
                    else:
                        # If not found in PR data, use the original case from users list
                        active_authors.append(user)

            authors = sorted(active_authors)
            logger.debug(f"  Final authors list: {authors}")

            # Write all metric sections
            self._write_metric_section(
                writer,
                "PR Count",
                months,
                authors,
                lambda m, a: sum(1 for pr in pr_data if self._matches_month_and_author(pr, m, a)),
            )

            self._write_metric_section(
                writer,
                "Reviews Participated (as Reviewer)",  # is:pr is:merged merged:YYYY-MM-DD..YYYY-MM-DD commenter:<username>
                months,
                authors,
                lambda m, a: getattr(review_metrics.get((m, a)), "reviews_participated", 0),
            )

            self._write_metric_section(
                writer,
                "PRs Approved (as Reviewer)",  # # is:pr is:merged merged:YYYY-MM-DD..YYYY-MM-DD reviewed-by:<username>
                months,
                authors,
                lambda m, a: getattr(review_metrics.get((m, a)), "reviews_approved", 0),
            )

            self._write_metric_section(
                writer,
                "Comments Made (as Reviewer)",  #  # is:pr is:merged merged:YYYY-MM-DD..YYYY-MM-DD commenter:<username> ... then count comments in each place
                months,
                authors,
                lambda m, a: getattr(review_metrics.get((m, a)), "comments_made", 0),
            )

            # Debug output for review metrics
            logger.debug("\nReview Metrics Summary:")
            for month in months:
                for author in authors:
                    key = (month, author)
                    if key in review_metrics:
                        metrics = review_metrics[key]
                        logger.debug(f"  {month} - {author}:")
                        logger.debug(f"    Reviews participated: {metrics.reviews_participated}")
                        logger.debug(f"    Reviews approved: {metrics.reviews_approved}")
                        logger.debug(f"    Comments made: {metrics.comments_made}")

            self._write_metric_section(
                writer,
                "Median Hours to Merge",
                months,
                authors,
                lambda m, a: (
                    round(
                        median(pr.hours_to_merge for pr in pr_data if self._matches_month_and_author(pr, m, a)),
                        2,
                    )
                    if any(self._matches_month_and_author(pr, m, a) for pr in pr_data)
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
                        sum(pr.hours_to_merge for pr in pr_data if self._matches_month_and_author(pr, m, a))
                        / len([pr for pr in pr_data if self._matches_month_and_author(pr, m, a)]),
                        2,
                    )
                    if any(self._matches_month_and_author(pr, m, a) for pr in pr_data)
                    else 0
                ),
            )

            # Add debug logging for average hours calculation
            logger.debug("\nAverage Hours to Merge Calculation:")
            for month in months:
                for author in authors:
                    key = (month, author)
                    if key in monthly_metrics:
                        metrics = monthly_metrics[key]
                        total_hours = sum(metrics.hours_to_merge)
                        count = len(metrics.hours_to_merge)
                        average = round(total_hours / count, 2) if count > 0 else 0
                        logger.debug(f"  {month} - {author}:")
                        logger.debug(f"    Total hours: {total_hours}")
                        logger.debug(f"    PR count: {count}")
                        logger.debug(f"    Average: {average}")
                        logger.debug(f"    Individual PRs:")
                        for repo, number, hours in sorted(metrics.pr_details, key=lambda x: x[2], reverse=True):
                            logger.debug(f"      {repo} #{number}: {hours:.2f} hours")

            self._write_metric_section(
                writer,
                "Median Lines Added",
                months,
                authors,
                lambda m, a: (
                    median(pr.additions for pr in pr_data if self._matches_month_and_author(pr, m, a))
                    if any(self._matches_month_and_author(pr, m, a) for pr in pr_data)
                    else 0
                ),
            )

            self._write_metric_section(
                writer,
                "Median Lines Removed",
                months,
                authors,
                lambda m, a: (
                    median(pr.deletions for pr in pr_data if self._matches_month_and_author(pr, m, a))
                    if any(self._matches_month_and_author(pr, m, a) for pr in pr_data)
                    else 0
                ),
            )

            self._write_metric_section(
                writer,
                "Median Files Changed",
                months,
                authors,
                lambda m, a: (
                    median(pr.changed_files for pr in pr_data if self._matches_month_and_author(pr, m, a))
                    if any(self._matches_month_and_author(pr, m, a) for pr in pr_data)
                    else 0
                ),
            )

            self._write_metric_section(
                writer,
                "Average Review Response Time (h) (as requested reviewer)",
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

            self._write_metric_section(
                writer,
                "Average Review Response Time (h) (for the author, until response by reviewer)",
                months,
                authors,
                lambda m, a: (
                    round(
                        sum(getattr(review_metrics.get((m, a)), "author_wait_times", []))
                        / len(getattr(review_metrics.get((m, a)), "author_wait_times", [])),
                        2,
                    )
                    if getattr(review_metrics.get((m, a)), "author_wait_times", [])
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
        self.api = GitHubAPI(token, users)
        self.users = users
        self.metrics_writers = {"pr": PRMetricsWriter("pr_metrics.csv", users)}
        # Cache for PR creation times
        self.pr_creation_times = {}

    def generate_reports(self, pr_data: List[PRData], monthly_metrics: dict, review_metrics: dict) -> None:
        """Generate all reports using the configured writers"""
        logger.info("Generating reports...")
        for writer in self.metrics_writers.values():
            writer.write(pr_data, monthly_metrics, review_metrics)
        logger.info("Reports generated successfully")

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
        pr_data = {}  # Use dict to track unique PRs by (repo, number)
        total_prs = 0

        for repo in repos:
            for user in users:
                prs = self.api.get_prs(repo, user, start_date, end_date)
                total_prs += len(prs)
                logger.info(f"Processing {len(prs)} PRs for {user} in {repo}")

                for pr in prs:
                    # Skip if we've already processed this PR
                    pr_key = (repo, pr["number"])
                    if pr_key in pr_data:
                        continue

                    details = self.api.get_pr_details(repo, pr["number"])
                    if details:
                        created_at = datetime.fromisoformat(details["created_at"].replace("Z", "+00:00"))
                        merged_at = datetime.fromisoformat(details["merged_at"].replace("Z", "+00:00"))
                        hours_to_merge = round((merged_at - created_at).total_seconds() / 3600, 2)

                        pr_data[pr_key] = PRData(
                            date=merged_at,
                            author=details["user"]["login"],
                            repo=repo,
                            number=details["number"],
                            additions=details["additions"],
                            deletions=details["deletions"],
                            changed_files=details["changed_files"],
                            hours_to_merge=hours_to_merge,
                        )

        logger.info(f"Completed PR data collection. Total unique PRs processed: {len(pr_data)}")
        return list(pr_data.values())

    def process_metrics(self, pr_data: List[PRData]) -> Tuple[dict, dict]:
        """Process PR data into monthly and review metrics"""
        logger.info("Starting metrics processing")
        monthly_metrics = {}
        review_metrics = {}

        for pr in pr_data:
            month = pr.date.strftime("%Y-%m")
            key = (month, self.api.normalize_username(pr.author))

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
            # Store PR details for debugging
            monthly_metrics[key].pr_details.append((pr.repo, pr.number, pr.hours_to_merge))

            # Process review data
            logger.debug(f"Processing reviews for PR #{pr.number} in {pr.repo}")
            review_data = self.api.get_pr_reviews(pr.repo, pr.number)
            self._process_review_data(review_data, month, review_metrics, monthly_metrics[key])

        logger.info("Completed metrics processing")
        return monthly_metrics, review_metrics

    def _convert_to_mst(self, dt: datetime) -> datetime:
        """Convert a datetime to Mountain Standard Time"""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        mst = pytz.timezone("America/Denver")
        return dt.astimezone(mst)

    def _process_review_data(
        self, review_data: dict, month: str, review_metrics: dict, author_metrics: MonthlyMetrics
    ) -> None:
        """Process review data and update metrics"""
        # Track which PRs each reviewer has commented on
        reviewer_commented_prs = set()

        # Get PR creation time for author wait time calculation
        reviews = review_data.get("reviews", [])
        if not reviews:
            logger.debug("No reviews found for this PR")
            return

        # First, process all reviews to track author wait times
        all_reviews = review_data["reviews"]
        for review in all_reviews:
            if review.get("submitted_at"):
                review_time = self._convert_to_mst(
                    datetime.fromisoformat(review["submitted_at"].replace("Z", "+00:00"))
                )
                review_month = review_time.strftime("%Y-%m")

                # Find the review request for this reviewer
                review_request = next(
                    (
                        req
                        for req in review_data["review_requests"]
                        if self.api.normalize_username(req.get("requested_reviewer", {}).get("login", ""))
                        == self.api.normalize_username(review["user"]["login"])
                    ),
                    None,
                )

                if review_request and review_request.get("created_at"):
                    request_time = self._convert_to_mst(
                        datetime.fromisoformat(review_request["created_at"].replace("Z", "+00:00"))
                    )
                    request_month = request_time.strftime("%Y-%m")

                    # Track the wait time from the author's perspective
                    author_key = (request_month, review_request.get("actor", {}).get("login"))
                    if author_key not in review_metrics:
                        review_metrics[author_key] = ReviewMetrics()
                    author_wait_time = (review_time - request_time).total_seconds() / 3600
                    review_metrics[author_key].author_wait_times.append(author_wait_time)
                    logger.debug(f"Author wait time calculation for {author_key[1]}:")
                    logger.debug(f"  Review submitted at: {review_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                    logger.debug(f"  Review requested at: {request_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                    logger.debug(f"  Wait time: {author_wait_time:.2f} hours")

        # Process all reviews and comments, then filter for specified users
        for review in reviews:
            reviewer = review["user"]["login"]
            if review.get("submitted_at"):
                review_time = self._convert_to_mst(
                    datetime.fromisoformat(review["submitted_at"].replace("Z", "+00:00"))
                )
                review_month = review_time.strftime("%Y-%m")
                key = (review_month, reviewer)
            else:
                key = (month, reviewer)  # Fallback to PR month if no review time

            if key not in review_metrics:
                review_metrics[key] = ReviewMetrics()

            # Count the review participation (only for formal reviews)
            review_metrics[key].reviews_participated += 1
            logger.debug(f"Review participation counted for {reviewer} - Review state: {review['state']}")

            # Count approvals
            if review["state"] == "APPROVED":
                review_metrics[key].reviews_approved += 1
                logger.debug(f"Review approval counted for {reviewer}")

            # Count review body comments (only once per PR)
            if review.get("body") and (reviewer, review["pull_request_url"]) not in reviewer_commented_prs:
                review_metrics[key].comments_made += 1
                reviewer_commented_prs.add((reviewer, review["pull_request_url"]))
                logger.debug(f"Review body comment counted for {reviewer} on PR {review['pull_request_url']}")

            # Update author metrics
            author_metrics.reviews_participated += 1

            # Calculate review response time from review request to review submission
            if review.get("submitted_at"):
                review_time = self._convert_to_mst(
                    datetime.fromisoformat(review["submitted_at"].replace("Z", "+00:00"))
                )
                # Find the review request for this reviewer
                review_request = next(
                    (
                        req
                        for req in review_data["review_requests"]
                        if self.api.normalize_username(req.get("requested_reviewer", {}).get("login", ""))
                        == self.api.normalize_username(reviewer)
                    ),
                    None,
                )

                if review_request and review_request.get("created_at"):
                    request_time = self._convert_to_mst(
                        datetime.fromisoformat(review_request["created_at"].replace("Z", "+00:00"))
                    )
                    response_time = (review_time - request_time).total_seconds() / 3600
                    if response_time >= 0:  # Only count positive response times
                        review_metrics[key].review_response_times.append(response_time)
                        logger.debug(f"Review response time calculation for {reviewer}:")
                        logger.debug(f"  Review submitted at: {review_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                        logger.debug(f"  Review requested at: {request_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                        logger.debug(f"  Response time: {response_time:.2f} hours")
                    else:
                        logger.warning(f"Negative response time detected for {reviewer}: {response_time:.2f} hours")
                        logger.warning(f"  Review submitted at: {review_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                        logger.warning(f"  Review requested at: {request_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")

        # Process review comments (inline comments)
        for comment in review_data["review_comments"]:
            try:
                if not isinstance(comment, dict):
                    logger.warning("Skipping invalid review comment format: %s", type(comment))
                    continue

                reviewer = comment.get("user", {}).get("login")
                if not reviewer:
                    logger.warning("Skipping review comment with no user login")
                    continue

                key = (month, reviewer)
                if key not in review_metrics:
                    review_metrics[key] = ReviewMetrics()

                # Count the comment (only once per PR)
                if (reviewer, comment["pull_request_url"]) not in reviewer_commented_prs:
                    review_metrics[key].comments_made += 1
                    reviewer_commented_prs.add((reviewer, comment["pull_request_url"]))
                    logger.debug("Review comment counted for %s on PR %s", reviewer, comment["pull_request_url"])
            except Exception as e:
                logger.warning("Error processing review comment: %s", str(e))
                continue

        # Process issue comments
        for comment in review_data["issue_comments"]:
            try:
                if not isinstance(comment, dict):
                    logger.warning("Skipping invalid issue comment format: %s", type(comment))
                    continue

                reviewer = comment.get("user", {}).get("login")
                if not reviewer:
                    logger.warning("Skipping issue comment with no user login")
                    continue

                key = (month, reviewer)
                if key not in review_metrics:
                    review_metrics[key] = ReviewMetrics()

                # Count the comment (only once per PR)
                if (reviewer, comment["issue_url"]) not in reviewer_commented_prs:
                    review_metrics[key].comments_made += 1
                    reviewer_commented_prs.add((reviewer, comment["issue_url"]))
                    logger.debug("Issue comment counted for %s on PR %s", reviewer, comment["issue_url"])
            except Exception as e:
                logger.warning("Error processing issue comment: %s", str(e))
                continue

        # Debug output for the current PR
        for reviewer in [self.api.normalize_username(u) for u in self.users]:
            key = (month, reviewer)
            if key in review_metrics:
                metrics = review_metrics[key]
                logger.debug(f"Metrics for {reviewer} in {month}:")
                logger.debug(f"  Reviews participated: {metrics.reviews_participated}")
                logger.debug(f"  Reviews approved: {metrics.reviews_approved}")
                logger.debug(f"  Comments made: {metrics.comments_made}")


def validate_github_token(token: str, test_repo: str) -> bool:
    """
    Validate GitHub token by making a test API call.
    Returns True if token is valid and has necessary permissions, False otherwise.

    Args:
        token: GitHub API token
        test_repo: Repository to test access against (format: 'owner/repo')
    """
    logger.info("Validating GitHub token...")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}

    try:
        # First check rate limits
        response = requests.get("https://api.github.com/rate_limit", headers=headers, timeout=30)
        if response.status_code == 200:
            rate_limit = response.json()
            core_limit = rate_limit["resources"]["core"]
            remaining = core_limit["remaining"]
            reset_time = datetime.fromtimestamp(core_limit["reset"])

            if remaining == 0:
                logger.error(
                    "GitHub API rate limit exceeded. Rate limit resets at %s",
                    reset_time.strftime("%Y-%m-%d %H:%M:%S UTC"),
                )
                return False
            else:
                logger.info(
                    "GitHub API rate limit: %d requests remaining, resets at %s",
                    remaining,
                    reset_time.strftime("%Y-%m-%d %H:%M:%S UTC"),
                )
        elif response.status_code == 403:
            # Try to parse rate limit info from the error response
            try:
                error_data = response.json()
                if "message" in error_data and "rate limit" in error_data["message"].lower():
                    logger.error("GitHub API rate limit exceeded: %s", error_data["message"])
                    if "documentation_url" in error_data:
                        logger.error("For more information, see: %s", error_data["documentation_url"])
                else:
                    logger.error("GitHub token validation failed: %s", response.text)
            except ValueError:
                logger.error("GitHub token validation failed: %s", response.text)
            return False
        else:
            logger.error("GitHub token validation failed: %s", response.text)
            return False

        # Then check if we can authenticate
        response = requests.get("https://api.github.com/user", headers=headers, timeout=30)
        if response.status_code != 200:
            logger.error("GitHub token validation failed: %s", response.text)
            return False

        # Then check if we have repo access by trying to access the first repo from the list
        response = requests.get(f"https://api.github.com/repos/{test_repo}", headers=headers, timeout=30)
        if response.status_code == 403:
            logger.error("GitHub token lacks repository access. Please ensure the token has 'repo' scope.")
            return False
        elif response.status_code != 200:
            logger.error("GitHub token validation failed: %s", response.text)
            return False

        logger.info("GitHub token validation successful")
        return True

    except requests.exceptions.RequestException as e:
        logger.error("Error validating GitHub token: %s", str(e))
        return False


def main():
    # Start timing
    start_time = datetime.now()
    
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
    repos = [r.strip() for r in args.repos.split(",")]

    # Get GitHub token
    token = os.getenv("GITHUB_TOKEN_READONLY_WEB")
    if not token:
        raise EnvironmentError("GITHUB_TOKEN_READONLY_WEB environment variable is not set.")

    # Validate GitHub token before proceeding
    if not validate_github_token(token, repos[0]):
        logger.error("GitHub token validation failed. Please check your token permissions and try again.")
        sys.exit(1)

    logger.info("Starting PR metrics collection")
    logger.info(f"Repos: {args.repos}")
    logger.info(f"Users: {args.users}")
    logger.info(f"Date range: {args.date_start} to {args.date_end}")

    # Initialize collector and process data
    collector = PRMetricsCollector(token, users)

    # Collect PR data
    pr_collection_start = datetime.now()
    pr_data = collector.collect_pr_data(repos, users, args.date_start, args.date_end)
    pr_collection_time = datetime.now() - pr_collection_start

    # Process metrics
    metrics_start = datetime.now()
    monthly_metrics, review_metrics = collector.process_metrics(pr_data)
    metrics_time = datetime.now() - metrics_start

    # Generate reports
    report_start = datetime.now()
    logger.info("Generating reports")
    collector.generate_reports(pr_data, monthly_metrics, review_metrics)
    report_time = datetime.now() - report_start

    # Calculate execution time
    end_time = datetime.now()
    execution_time = end_time - start_time

    def format_time(delta):
        hours, remainder = divmod(delta.total_seconds(), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{int(hours)}h {int(minutes)}m {int(seconds)}s"

    # Log summary
    logger.info("\nSummary:")
    logger.info(f"✓ Total PRs processed: {len(pr_data)}")
    logger.info(f"✓ Date range: {args.date_start} to {args.date_end}")
    logger.info(f"✓ Repositories processed: {len(repos)}")
    logger.info(f"✓ Users analyzed: {len(users)}")
    logger.info(f"✓ Output file: {args.output}")
    logger.info("\nTiming Details:")
    logger.info(f"✓ PR Collection: {format_time(pr_collection_time)}")
    logger.info(f"✓ Metrics Processing: {format_time(metrics_time)}")
    logger.info(f"✓ Report Generation: {format_time(report_time)}")
    logger.info(f"✓ Total Execution Time: {format_time(execution_time)}")


if __name__ == "__main__":
    main()
