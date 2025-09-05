#!/usr/bin/env python3

"""
GitHub Pull Request Metrics Generator (Enhanced)
===============================================

This script generates detailed PR metrics reports for specified GitHub repositories and users.
Enhanced with robust input validation, comprehensive error handling, and caching.

Output Files
-----------
1. pr_metrics.csv:
   Detailed data for each PR including date, author, repository, PR number, lines changed,
   and time to merge.

Requirements
-----------
- Python 3.7+
- GitHub Personal Access Token with repo access
- Required Python packages: requests, python-dotenv

Environment Variables
-------------------
GITHUB_TOKEN_READONLY_WEB: GitHub Personal Access Token

Usage
-----
python3 developer_activity_insight.py --owner myorg --repos 'repo1,repo2' \
                                     --users 'user1,user2' \
                                     --date_start '2024-01-01' \
                                     --date_end '2024-12-31' \
                                     [--output pr_metrics.csv]

Arguments
---------
--owner:       GitHub organization or user that owns repositories (required)
--repos:       Comma-separated list of repos (can be just names if same owner)
--users:       Comma-separated list of GitHub usernames
--date_start:  Start date in YYYY-MM-DD format
--date_end:    End date in YYYY-MM-DD format
--output:      Output CSV file name (default: pr_metrics.csv)
--dry-run:     Validate inputs and setup without collecting data
"""

# Standard library imports
import argparse
import csv
import json
import logging
import os
import random
import sys
import time
import urllib.parse
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Dict, List, Set, Tuple, Optional, Any

# Third-party imports
import requests
from dotenv import load_dotenv
import pytz

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Custom exception for validation errors"""
    pass


class GitHubAPIError(Exception):
    """Custom exception for GitHub API errors"""
    pass


@dataclass
class ValidatedInputs:
    """Container for validated and normalized inputs"""
    owner: str
    repos: List[str]  # Full owner/repo format
    users: List[str]  # Original case preserved
    normalized_users: List[str]  # Lowercase for comparisons
    start_date: datetime  # UTC
    end_date: datetime  # UTC
    output_file: str
    debug: bool
    dry_run: bool


@dataclass
class RepoInfo:
    """Information about a repository"""
    name: str
    default_branch: str
    visibility: str
    permissions: Dict[str, bool]
    accessible: bool


@dataclass
class UserInfo:
    """Information about a GitHub user"""
    login: str
    id: int
    type: str
    exists: bool


def normalize_inputs(args) -> ValidatedInputs:
    """
    Normalize and validate all inputs with comprehensive error checking.
    
    Args:
        args: Parsed command line arguments
        
    Returns:
        ValidatedInputs object with normalized data
        
    Raises:
        ValidationError: If any input is invalid
    """
    logger.info("Validating and normalizing inputs...")
    
    # Validate owner
    if not hasattr(args, 'owner') or not args.owner:
        raise ValidationError("--owner is required")
    owner = args.owner.strip()
    if not owner:
        raise ValidationError("Owner cannot be empty")
    if '/' in owner:
        raise ValidationError("Owner should not contain '/', use --repos for full repo names")
    
    # Validate and normalize repos
    if not args.repos:
        raise ValidationError("--repos is required")
    
    raw_repos = [r.strip() for r in args.repos.split(",") if r.strip()]
    if not raw_repos:
        raise ValidationError("At least one repository must be specified")
    
    repos = []
    for repo in raw_repos:
        if not repo:
            continue
        if '/' not in repo:
            repo = f"{owner}/{repo}"
        elif repo.count('/') != 1:
            raise ValidationError(f"Invalid repo format: {repo}. Expected 'owner/repo'")
        repos.append(repo)
    
    if not repos:
        raise ValidationError("No valid repositories found after normalization")
    
    # Validate and normalize users
    if not args.users:
        raise ValidationError("--users is required")
    
    raw_users = [u.strip() for u in args.users.split(",") if u.strip()]
    if not raw_users:
        raise ValidationError("At least one user must be specified")
    
    users = [u for u in raw_users if u]  # Original case preserved
    normalized_users = [u.lower() for u in users]  # For comparisons
    
    if not users:
        raise ValidationError("No valid users found after normalization")
    
    # Validate dates
    try:
        start_date = datetime.fromisoformat(args.date_start).replace(tzinfo=timezone.utc)
    except ValueError as e:
        raise ValidationError(f"Invalid start date format: {args.date_start}. Expected YYYY-MM-DD. Error: {e}")
    
    try:
        end_date = datetime.fromisoformat(args.date_end).replace(tzinfo=timezone.utc)
    except ValueError as e:
        raise ValidationError(f"Invalid end date format: {args.date_end}. Expected YYYY-MM-DD. Error: {e}")
    
    if start_date >= end_date:
        raise ValidationError("date_start must be before date_end")
    
    # Validate date range isn't too large (prevent abuse)
    days_diff = (end_date - start_date).days
    if days_diff > 730:  # 2 years
        logger.warning(f"Large date range detected: {days_diff} days. This may take a long time.")
    
    # Validate output file
    output_file = args.output.strip() if args.output else "pr_metrics.csv"
    if not output_file.endswith('.csv'):
        output_file += '.csv'
    
    # Check if output directory exists and is writable
    output_path = Path(output_file)
    if output_path.parent != Path('.'):
        output_path.parent.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"✓ Normalized {len(repos)} repositories")
    logger.info(f"✓ Normalized {len(users)} users")
    logger.info(f"✓ Date range: {start_date.date()} to {end_date.date()} ({days_diff} days)")
    logger.info(f"✓ Output file: {output_file}")
    
    return ValidatedInputs(
        owner=owner,
        repos=repos,
        users=users,
        normalized_users=normalized_users,
        start_date=start_date,
        end_date=end_date,
        output_file=output_file,
        debug=getattr(args, 'debug', False),
        dry_run=getattr(args, 'dry_run', False)
    )


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
    created_at: datetime
    ready_for_review_at: datetime
    merged_at: datetime


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
    pr_details: List[Tuple[str, int, float, datetime, datetime, datetime]] = field(default_factory=list)  # (repo, number, hours, created_at, ready_for_review_at, merged_at)


@dataclass
class ReviewMetrics:
    """Data class to hold review metrics for an author"""

    reviews_participated: int = 0
    reviews_approved: int = 0
    comments_made: int = 0
    review_response_times: List[float] = field(default_factory=list)
    author_wait_times: List[float] = field(default_factory=list)  # Time authors wait for reviews


def gh_request(session: requests.Session, method: str, url: str, **kwargs) -> requests.Response:
    """
    Make a GitHub API request with comprehensive retry logic and rate limiting.
    
    Args:
        session: Requests session with headers configured
        method: HTTP method
        url: Request URL
        **kwargs: Additional request parameters
        
    Returns:
        Response object
        
    Raises:
        GitHubAPIError: If request fails after all retries
    """
    max_tries = 6
    backoff = 1.0
    
    for attempt in range(1, max_tries + 1):
        try:
            logger.debug(f"Making {method} request to {url} (attempt {attempt})")
            r = session.request(method, url, timeout=30, **kwargs)
            
            # Handle rate limiting
            if r.status_code == 429:
                retry_after = r.headers.get("Retry-After")
                if retry_after:
                    sleep_time = float(retry_after)
                    logger.warning(f"Rate limited. Waiting {sleep_time} seconds (Retry-After header)")
                else:
                    sleep_time = backoff + random.uniform(0, 1)
                    logger.warning(f"Rate limited. Waiting {sleep_time:.1f} seconds (exponential backoff)")
                
                time.sleep(sleep_time)
                backoff = min(backoff * 2, 60)
                continue
            
            # Handle server errors
            if r.status_code in (502, 503, 504):
                retry_after = r.headers.get("Retry-After")
                sleep_time = float(retry_after) if retry_after else backoff + random.uniform(0, 1)
                logger.warning(f"Server error {r.status_code}. Waiting {sleep_time:.1f} seconds")
                time.sleep(sleep_time)
                backoff = min(backoff * 2, 60)
                continue
            
            # Handle abuse detection
            if r.status_code == 403:
                if "abuse" in r.text.lower() or "secondary rate limit" in r.text.lower():
                    retry_after = r.headers.get("Retry-After")
                    sleep_time = float(retry_after) if retry_after else 30
                    logger.warning(f"Abuse detection triggered. Waiting {sleep_time} seconds")
                    time.sleep(sleep_time)
                    continue
                # If not abuse, let it fall through to return the response
            
            # Log rate limit status
            if 'X-RateLimit-Remaining' in r.headers:
                remaining = r.headers.get('X-RateLimit-Remaining')
                reset_time = r.headers.get('X-RateLimit-Reset')
                if reset_time:
                    reset_dt = datetime.fromtimestamp(int(reset_time))
                    logger.debug(f"Rate limit: {remaining} remaining, resets at {reset_dt}")
            
            return r
            
        except requests.exceptions.RequestException as e:
            if attempt == max_tries:
                raise GitHubAPIError(f"Request failed after {max_tries} attempts: {e}")
            
            sleep_time = backoff + random.uniform(0, 1)
            logger.warning(f"Request exception: {e}. Retrying in {sleep_time:.1f} seconds")
            time.sleep(sleep_time)
            backoff = min(backoff * 2, 60)
    
    raise GitHubAPIError(f"Request failed after {max_tries} attempts")


def validate_github_auth_and_scopes(token: str) -> Tuple[Dict[str, Any], Set[str]]:
    """
    Validate GitHub token and extract OAuth scopes.
    
    Args:
        token: GitHub API token
        
    Returns:
        Tuple of (user_info, scopes_set)
        
    Raises:
        GitHubAPIError: If authentication fails or token is invalid
    """
    logger.info("Validating GitHub authentication and scopes...")
    
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "PR-Metrics-Collector/1.0"
    })
    
    try:
        # Check rate limits first
        logger.debug("Checking rate limits...")
        r = gh_request(session, "GET", "https://api.github.com/rate_limit")
        r.raise_for_status()
        
        rate_data = r.json()
        core_limit = rate_data["resources"]["core"]
        search_limit = rate_data["resources"]["search"]
        
        logger.info(f"✓ Core API: {core_limit['remaining']}/{core_limit['limit']} remaining")
        logger.info(f"✓ Search API: {search_limit['remaining']}/{search_limit['limit']} remaining")
        
        if core_limit['remaining'] < 100:
            reset_time = datetime.fromtimestamp(core_limit['reset'])
            logger.warning(f"Low rate limit remaining. Resets at {reset_time}")
        
        if search_limit['remaining'] < 10:
            reset_time = datetime.fromtimestamp(search_limit['reset'])
            raise GitHubAPIError(f"Insufficient search API quota. Resets at {reset_time}")
        
        # Authenticate and get user info
        logger.debug("Authenticating user...")
        r = gh_request(session, "GET", "https://api.github.com/user")
        r.raise_for_status()
        
        user_info = r.json()
        logger.info(f"✓ Authenticated as: {user_info['login']} (ID: {user_info['id']})")
        
        # Extract OAuth scopes
        scopes_header = r.headers.get('X-OAuth-Scopes', '')
        scopes = {scope.strip() for scope in scopes_header.split(',') if scope.strip()}
        
        logger.info(f"✓ OAuth scopes: {', '.join(sorted(scopes)) if scopes else 'none'}")
        
        # Check for required scopes
        required_scopes = {'repo', 'read:org'}  # repo for private repos, read:org for org membership
        missing_scopes = required_scopes - scopes
        
        if missing_scopes:
            logger.warning(f"Missing recommended scopes: {', '.join(missing_scopes)}")
            logger.warning("This may limit access to private repositories or org information")
        else:
            logger.info("✓ All recommended scopes present")
        
        return user_info, scopes
        
    except requests.exceptions.RequestException as e:
        raise GitHubAPIError(f"Authentication failed: {e}")


def validate_repositories(session: requests.Session, repos: List[str]) -> Dict[str, RepoInfo]:
    """
    Validate access to all specified repositories.
    
    Args:
        session: Authenticated requests session
        repos: List of repository names in owner/repo format
        
    Returns:
        Dictionary mapping repo names to RepoInfo objects
        
    Raises:
        GitHubAPIError: If any repository is inaccessible
    """
    logger.info(f"Validating access to {len(repos)} repositories...")
    
    repo_info = {}
    inaccessible_repos = []
    
    for repo in repos:
        logger.debug(f"Checking repository: {repo}")
        
        try:
            r = gh_request(session, "GET", f"https://api.github.com/repos/{repo}")
            
            if r.status_code == 404:
                logger.error(f"✗ Repository not found: {repo}")
                inaccessible_repos.append((repo, "Not found (404)"))
                continue
            elif r.status_code == 403:
                logger.error(f"✗ Access denied to repository: {repo}")
                inaccessible_repos.append((repo, "Access denied (403)"))
                continue
            
            r.raise_for_status()
            data = r.json()
            
            repo_info[repo] = RepoInfo(
                name=repo,
                default_branch=data.get('default_branch', 'main'),
                visibility=data.get('visibility', 'unknown'),
                permissions=data.get('permissions', {}),
                accessible=True
            )
            
            logger.info(f"✓ {repo} ({data.get('visibility', 'unknown')}, default: {data.get('default_branch', 'main')})")
            
        except Exception as e:
            logger.error(f"✗ Error accessing {repo}: {e}")
            inaccessible_repos.append((repo, str(e)))
    
    if inaccessible_repos:
        logger.error("\nRepository access issues found:")
        for repo, reason in inaccessible_repos:
            logger.error(f"  {repo}: {reason}")
        raise GitHubAPIError(f"Cannot access {len(inaccessible_repos)} repositories")
    
    logger.info(f"✓ All {len(repos)} repositories accessible")
    return repo_info


def validate_users(session: requests.Session, users: List[str]) -> Dict[str, UserInfo]:
    """
    Validate that all specified users exist on GitHub.
    
    Args:
        session: Authenticated requests session
        users: List of GitHub usernames
        
    Returns:
        Dictionary mapping usernames to UserInfo objects
        
    Raises:
        GitHubAPIError: If any user doesn't exist
    """
    logger.info(f"Validating {len(users)} users...")
    
    user_info = {}
    missing_users = []
    
    for user in users:
        logger.debug(f"Checking user: {user}")
        
        try:
            r = gh_request(session, "GET", f"https://api.github.com/users/{user}")
            
            if r.status_code == 404:
                logger.error(f"✗ User not found: {user}")
                missing_users.append(user)
                continue
            
            r.raise_for_status()
            data = r.json()
            
            user_info[user] = UserInfo(
                login=data['login'],  # Use the canonical case from GitHub
                id=data['id'],
                type=data.get('type', 'User'),
                exists=True
            )
            
            logger.info(f"✓ {data['login']} (ID: {data['id']}, Type: {data.get('type', 'User')})")
            
        except Exception as e:
            logger.error(f"✗ Error checking user {user}: {e}")
            missing_users.append(user)
    
    if missing_users:
        logger.error(f"\nMissing users: {', '.join(missing_users)}")
        raise GitHubAPIError(f"Cannot find {len(missing_users)} users")
    
    logger.info(f"✓ All {len(users)} users found")
    return user_info




def dry_run_validation(inputs: ValidatedInputs, token: str) -> bool:
    """
    Perform a comprehensive dry run validation without collecting data.
    
    Args:
        inputs: Validated input parameters
        token: GitHub API token
        
    Returns:
        True if all validations pass, False otherwise
    """
    logger.info("=" * 60)
    logger.info("STARTING DRY RUN VALIDATION")
    logger.info("=" * 60)
    
    try:
        # Setup session
        session = requests.Session()
        session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "PR-Metrics-Collector/1.0"
        })
        
        # 1. Validate authentication and scopes
        logger.info("\n1. Validating GitHub authentication...")
        user_info, scopes = validate_github_auth_and_scopes(token)
        
        # 2. Validate repositories
        logger.info("\n2. Validating repository access...")
        repo_info = validate_repositories(session, inputs.repos)
        
        # 3. Validate users
        logger.info("\n3. Validating users...")
        user_info_dict = validate_users(session, inputs.users)
        
        # 4. Test a small search query
        logger.info("\n4. Testing search API...")
        test_repo = inputs.repos[0]
        test_user = inputs.users[0]
        
        # Test search with a very limited date range
        test_start = inputs.start_date.strftime('%Y-%m-%d')
        test_end = (inputs.start_date.replace(day=min(inputs.start_date.day + 1, 28))).strftime('%Y-%m-%d')
        
        search_query = f"repo:{test_repo} is:pr author:{test_user} created:{test_start}..{test_end}"
        search_url = "https://api.github.com/search/issues"
        
        logger.debug(f"Test search query: {search_query}")
        r = gh_request(session, "GET", search_url, params={"q": search_query, "per_page": 1})
        r.raise_for_status()
        
        search_data = r.json()
        logger.info(f"✓ Search API working. Found {search_data.get('total_count', 0)} PRs in test range")
        
        # Summary
        logger.info("\n" + "=" * 60)
        logger.info("DRY RUN VALIDATION SUMMARY")
        logger.info("=" * 60)
        logger.info(f"✓ Authentication: {user_info['login']}")
        logger.info(f"✓ OAuth scopes: {len(scopes)} scopes")
        logger.info(f"✓ Repositories: {len(repo_info)} accessible")
        logger.info(f"✓ Users: {len(user_info_dict)} found")
        logger.info(f"✓ Search API: Working")
        logger.info(f"✓ Date range: {inputs.start_date.date()} to {inputs.end_date.date()}")
        logger.info("\n✅ All validations passed! Ready to collect data.")
        
        return True
        
    except Exception as e:
        logger.error(f"\n❌ Dry run validation failed: {e}")
        return False


class GitHubAPI:
    """Handles all GitHub API interactions with robust error handling"""

    def __init__(self, token: str, users: List[str]):
        self.base_url = "https://api.github.com"
        self.users = users
        self.cache = {}  # Simple cache for API responses
        
        # Setup session with robust headers
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "PR-Metrics-Collector/1.0"
        })

    def normalize_username(self, username: str) -> str:
        """Normalize username to lowercase for consistent comparison"""
        return Utils.normalize_username(username)

    def _make_request(self, url: str, params: dict = None) -> Optional[dict]:
        """Make an API request using the robust gh_request function"""
        # Check cache first
        cache_key = f"{url}?{urllib.parse.urlencode(params) if params else ''}"
        if cache_key in self.cache:
            logger.debug(f"Using cached response for {cache_key}")
            return self.cache[cache_key]

        try:
            response = gh_request(self.session, "GET", url, params=params)
            response.raise_for_status()
            data = response.json()
            
            # Cache successful response
            self.cache[cache_key] = data
            return data
            
        except Exception as e:
            logger.error(f"Request to {url} failed: {e}")
            return None

    def get_prs(self, repo: str, author: str, start_date: str, end_date: str) -> List[dict]:
        """Fetch PRs for a given repo and author"""
        logger.info(f"Fetching PRs for {author} in {repo}")
        search_url = f"{self.base_url}/search/issues"
        unique_prs = {}  # Use a dict to track unique PRs by number

        # Search for PRs authored by the user
        author_query = f"repo:{repo} is:pr is:merged author:{author} merged:{start_date}..{end_date}"
        logger.debug(f"Author query: {author_query}")
        data = self._make_request(search_url, params={"q": author_query, "per_page": 100, "page": 1})
        if data:
            author_prs = data.get("items", [])
            logger.info(f"Found {len(author_prs)} PRs authored by {author} in {repo}")
            for pr in author_prs:
                unique_prs[pr["number"]] = pr

        # Search for PRs reviewed by the user
        reviewer_query = f"repo:{repo} is:pr is:merged review-requested:{author} merged:{start_date}..{end_date}"
        logger.debug(f"Reviewer query: {reviewer_query}")
        data = self._make_request(search_url, params={"q": reviewer_query, "per_page": 100, "page": 1})
        if data:
            reviewer_prs = data.get("items", [])
            logger.info(f"Found {len(reviewer_prs)} PRs reviewed by {author} in {repo}")
            for pr in reviewer_prs:
                unique_prs[pr["number"]] = pr

        # Search for PRs where user commented
        commenter_query = f"repo:{repo} is:pr is:merged commenter:{author} merged:{start_date}..{end_date}"
        logger.debug(f"Commenter query: {commenter_query}")
        data = self._make_request(search_url, params={"q": commenter_query, "per_page": 100, "page": 1})
        if data:
            commenter_prs = data.get("items", [])
            logger.info(f"Found {len(commenter_prs)} PRs commented on by {author} in {repo}")
            for pr in commenter_prs:
                unique_prs[pr["number"]] = pr

        # Convert dict values to list
        pr_list = list(unique_prs.values())
        logger.info(f"Total unique PRs found for {author} in {repo}: {len(pr_list)}")
        return pr_list

    def get_pr_details(self, repo: str, pr_number: int) -> Optional[dict]:
        """Fetch detailed PR information"""
        logger.debug(f"Fetching details for PR #{pr_number} in {repo}")
        pr_url = f"{self.base_url}/repos/{repo}/pulls/{pr_number}"
        return self._make_request(pr_url)

    def get_pr_reviews(self, repo: str, pr_number: int) -> dict:
        """Fetch all review-related data for a PR"""
        logger.debug(f"Fetching reviews for PR #{pr_number} in {repo}")
        base_url = f"{self.base_url}/repos/{repo}/pulls/{pr_number}"

        try:
            # Fetch all reviews and comments using robust requests
            all_reviews = self._make_request(f"{base_url}/reviews") or []
            all_comments = self._make_request(f"{base_url}/comments") or []
            all_issue_comments = self._make_request(
                f"{base_url.replace('/pulls/', '/issues/')}/comments"
            ) or []

            # Fetch review request events
            events_url = f"{base_url.replace('/pulls/', '/issues/')}/events"
            all_events = self._make_request(events_url) or []
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
        except Exception as e:
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
                    key = (month, self.normalize_username(author))
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
                        for repo, number, hours, created_at, ready_for_review_at, merged_at in sorted(metrics.pr_details, key=lambda x: x[2], reverse=True):
                            logger.debug(f"      {repo} #{number}: {hours:.2f} hours")
                            logger.debug(f"        Created: {created_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                            logger.debug(f"        Ready for review: {ready_for_review_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                            logger.debug(f"        Merged:  {merged_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")

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
                        ready_for_review_at = datetime.fromisoformat(details["ready_for_review_at"].replace("Z", "+00:00")) if details.get("ready_for_review_at") else created_at
                        merged_at = datetime.fromisoformat(details["merged_at"].replace("Z", "+00:00")) if details.get("merged_at") else None

                        if not merged_at:
                            continue

                        hours_to_merge = round((merged_at - ready_for_review_at).total_seconds() / 3600, 2)

                        # Add debug logging for ready_for_review_at
                        if not details.get("ready_for_review_at"):
                            logger.warning(f"PR #{pr['number']} in {repo} has no ready_for_review_at, using created_at: {created_at}")
                        else:
                            logger.warning(f"PR #{pr['number']} in {repo} ready_for_review_at: {ready_for_review_at}")

                        pr_data[pr_key] = PRData(
                            date=merged_at,
                            author=details["user"]["login"],
                            repo=repo,
                            number=details["number"],
                            additions=details["additions"],
                            deletions=details["deletions"],
                            changed_files=details["changed_files"],
                            hours_to_merge=hours_to_merge,
                            created_at=created_at,
                            ready_for_review_at=ready_for_review_at,
                            merged_at=merged_at,
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
            monthly_metrics[key].pr_details.append((pr.repo, pr.number, pr.hours_to_merge, pr.created_at, pr.ready_for_review_at, pr.merged_at))

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
    """Enhanced main function with robust validation and error handling"""
    start_time = datetime.now()
    
    # Load environment variables
    load_dotenv()
    
    # Parse arguments
    parser = argparse.ArgumentParser(
        description="Fetch PR metrics from GitHub with robust validation and error handling.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage
  python3 developer_activity_insight.py --owner myorg --repos "repo1,repo2" --users "user1,user2" --date_start "2024-01-01" --date_end "2024-12-31"
  
  # With full repo names
  python3 developer_activity_insight.py --owner myorg --repos "myorg/repo1,otherorg/repo2" --users "user1,user2" --date_start "2024-01-01" --date_end "2024-12-31"
  
  # Dry run validation only
  python3 developer_activity_insight.py --owner myorg --repos "repo1" --users "user1" --date_start "2024-01-01" --date_end "2024-12-31" --dry-run
        """
    )
    
    parser.add_argument("--owner", required=True, 
                       help="GitHub organization or user that owns repositories")
    parser.add_argument("--repos", required=True, 
                       help="Comma-separated list of repositories (can be just names if same owner)")
    parser.add_argument("--users", required=True, 
                       help="Comma-separated list of GitHub usernames to analyze")
    parser.add_argument("--date_start", required=True, 
                       help="Start date in YYYY-MM-DD format")
    parser.add_argument("--date_end", required=True, 
                       help="End date in YYYY-MM-DD format")
    parser.add_argument("--output", default="pr_metrics.csv", 
                       help="Output CSV file name (default: pr_metrics.csv)")
    parser.add_argument("--debug", action="store_true", 
                       help="Enable debug logging")
    parser.add_argument("--dry-run", action="store_true", 
                       help="Validate inputs and setup without collecting data")
    
    try:
        args = parser.parse_args()
        
        # Set logging level
        if args.debug:
            logger.setLevel(logging.DEBUG)
            logging.getLogger('requests').setLevel(logging.DEBUG)
        
        # Validate and normalize inputs
        try:
            inputs = normalize_inputs(args)
        except ValidationError as e:
            logger.error(f"Input validation failed: {e}")
            sys.exit(1)
        
        # Get GitHub token
        token = os.getenv("GITHUB_TOKEN_READONLY_WEB")
        if not token:
            logger.error("GITHUB_TOKEN_READONLY_WEB environment variable is not set")
            logger.error("Please set your GitHub Personal Access Token in the environment")
            sys.exit(1)
        
        # Perform dry run validation
        if inputs.dry_run:
            success = dry_run_validation(inputs, token)
            sys.exit(0 if success else 1)
        
        # If not dry run, do a quick validation anyway
        logger.info("Performing preflight validation...")
        if not dry_run_validation(inputs, token):
            logger.error("Preflight validation failed. Use --dry-run for detailed diagnostics.")
            sys.exit(1)
        
        logger.info("\n" + "=" * 60)
        logger.info("STARTING DATA COLLECTION")
        logger.info("=" * 60)
        
        # Initialize collector and process data with validated inputs
        collector = PRMetricsCollector(token, inputs.users)
        collector.metrics_writers = {"pr": PRMetricsWriter(inputs.output_file, inputs.users)}

        # Collect PR data
        pr_collection_start = datetime.now()
        pr_data = collector.collect_pr_data(inputs.repos, inputs.users, 
                                           inputs.start_date.strftime('%Y-%m-%d'), 
                                           inputs.end_date.strftime('%Y-%m-%d'))
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
        logger.info("\n" + "=" * 60)
        logger.info("EXECUTION SUMMARY")
        logger.info("=" * 60)
        logger.info(f"✓ Total PRs processed: {len(pr_data)}")
        logger.info(f"✓ Date range: {inputs.start_date.date()} to {inputs.end_date.date()}")
        logger.info(f"✓ Repositories processed: {len(inputs.repos)}")
        logger.info(f"✓ Users analyzed: {len(inputs.users)}")
        logger.info(f"✓ Output file: {inputs.output_file}")
        logger.info("\nTiming Details:")
        logger.info(f"✓ PR Collection: {format_time(pr_collection_time)}")
        logger.info(f"✓ Metrics Processing: {format_time(metrics_time)}")
        logger.info(f"✓ Report Generation: {format_time(report_time)}")
        logger.info(f"✓ Total Execution Time: {format_time(execution_time)}")
        
        logger.info("\n🎉 PR metrics collection completed successfully!")
        
    except KeyboardInterrupt:
        logger.info("\n⚠️  Operation cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        if hasattr(args, 'debug') and args.debug:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
