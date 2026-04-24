"""Generic GitHub merged-PR throughput collection for engineering sheets."""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import requests

from engineering_throughput.config import read_env_file
from engineering_throughput.models import GitHubCollection, RepoAccessIssue, RunConfig


GRAPHQL_URL = "https://api.github.com/graphql"
REST_URL = "https://api.github.com"
LARGE_PR_LINES = 1000
SLOW_MERGE_HOURS = 72
MAX_GRAPHQL_SEARCH_RESULTS = 1000


@dataclass(frozen=True)
class MonthWindow:
    """A bounded month window used for GitHub search pagination."""

    label: str
    start: date
    end: date


def month_windows(start: date, end: date) -> tuple[MonthWindow, ...]:
    """Split an inclusive date range into month windows."""

    current = date(start.year, start.month, 1)
    windows: list[MonthWindow] = []
    while current <= end:
        if current.month == 12:
            next_month = date(current.year + 1, 1, 1)
        else:
            next_month = date(current.year, current.month + 1, 1)
        window_start = max(current, start)
        window_end = min(next_month - timedelta(days=1), end)
        windows.append(MonthWindow(label=current.strftime("%Y-%m"), start=window_start, end=window_end))
        current = next_month
    return tuple(windows)


def iso_to_datetime(value: str | None) -> datetime | None:
    """Convert GitHub ISO timestamps to timezone-aware datetimes."""

    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def hours_between(start: datetime | None, end: datetime | None) -> float | None:
    """Return rounded hours between two optional datetimes."""

    if start is None or end is None:
        return None
    return round((end - start).total_seconds() / 3600, 2)


def github_token(config: RunConfig) -> str:
    """Resolve a GitHub token from `gh auth token`, env file, or process env."""

    try:
        token = subprocess.check_output(["gh", "auth", "token"], text=True).strip()
        if token:
            return token
    except (OSError, subprocess.CalledProcessError):
        pass

    env_values = read_env_file(config.env_file)
    for key in ("GITHUB_TOKEN", "GITHUB_TOKEN_READONLY_WEB", "GH_TOKEN"):
        if env_values.get(key):
            return env_values[key]
        if os.environ.get(key):
            return os.environ[key]
    raise RuntimeError("No GitHub token found in active gh auth, env file, or process env")


class GitHubClient:
    """Small GitHub client wrapper for repo validation and GraphQL search."""

    def __init__(self, token: str):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    def validate_repo(self, owner: str, repo: str) -> tuple[bool, str, str]:
        response = self.session.get(f"{REST_URL}/repos/{owner}/{repo}", timeout=30)
        if response.status_code == 200:
            payload = response.json()
            canonical_name = payload.get("name", repo)
            if payload.get("archived"):
                return False, canonical_name, "archived"
            return True, canonical_name, ""
        return False, repo, f"{response.status_code} {response.reason}"

    def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(1, 5):
            response = self.session.post(
                GRAPHQL_URL,
                json={"query": query, "variables": variables},
                timeout=60,
            )
            if response.status_code in {502, 503, 504} and attempt < 4:
                time.sleep(2 * attempt)
                continue
            response.raise_for_status()
            payload = response.json()
            if "errors" in payload:
                messages = "; ".join(error.get("message", "unknown error") for error in payload["errors"])
                if attempt < 4 and any(term in messages.lower() for term in ("timeout", "temporarily", "server")):
                    time.sleep(2 * attempt)
                    continue
                raise RuntimeError(messages)
            return payload["data"]
        raise RuntimeError("GraphQL request failed after retries")

    def search_merged_prs(self, owner: str, repo: str, window: MonthWindow) -> list[dict[str, Any]]:
        query = """
        query($query: String!, $cursor: String) {
          search(type: ISSUE, query: $query, first: 100, after: $cursor) {
            issueCount
            pageInfo { hasNextPage endCursor }
            nodes {
              ... on PullRequest {
                number
                title
                url
                createdAt
                mergedAt
                additions
                deletions
                changedFiles
                author { login }
                reviews(first: 100) {
                  nodes {
                    state
                    submittedAt
                    author { login }
                  }
                }
              }
            }
          }
        }
        """
        return self._search_merged_prs_range(owner, repo, window, query, window.start, window.end)

    def _search_merged_prs_range(
        self,
        owner: str,
        repo: str,
        window: MonthWindow,
        query: str,
        range_start: date,
        range_end: date,
    ) -> list[dict[str, Any]]:
        query_text = f"repo:{owner}/{repo} is:pr is:merged merged:{range_start.isoformat()}..{range_end.isoformat()}"
        cursor = None
        rows: list[dict[str, Any]] = []
        first_page = True
        while True:
            data = self.graphql(query, {"query": query_text, "cursor": cursor})
            search = data["search"]
            if first_page:
                issue_count = int(search.get("issueCount") or 0)
                if issue_count > MAX_GRAPHQL_SEARCH_RESULTS:
                    if range_start >= range_end:
                        raise RuntimeError(
                            "GitHub search returned more than 1000 merged PRs for "
                            f"{owner}/{repo} on {range_start.isoformat()}; narrow the date range"
                        )
                    midpoint = range_start + timedelta(days=(range_end - range_start).days // 2)
                    left = self._search_merged_prs_range(owner, repo, window, query, range_start, midpoint)
                    right = self._search_merged_prs_range(
                        owner,
                        repo,
                        window,
                        query,
                        midpoint + timedelta(days=1),
                        range_end,
                    )
                    return left + right
                first_page = False
            rows.extend([node for node in search["nodes"] if node])
            page_info = search["pageInfo"]
            if not page_info["hasNextPage"]:
                break
            cursor = page_info["endCursor"]
        return rows


def row_from_pr(owner: str, repo: str, window: MonthWindow, pr: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize one GitHub PR node into a JSON-safe throughput row."""

    created_at = iso_to_datetime(pr.get("createdAt"))
    merged_at = iso_to_datetime(pr.get("mergedAt"))
    if created_at is None or merged_at is None:
        return None

    reviews = pr.get("reviews", {}).get("nodes", []) or []
    review_times: list[datetime] = []
    approval_times: list[datetime] = []
    approval_count = 0
    reviewers: set[str] = set()
    for review in reviews:
        review_author = (review.get("author") or {}).get("login")
        if review_author:
            reviewers.add(review_author)
        submitted_at = iso_to_datetime(review.get("submittedAt"))
        if submitted_at:
            review_times.append(submitted_at)
        if review.get("state") == "APPROVED":
            approval_count += 1
            if submitted_at:
                approval_times.append(submitted_at)

    lines_changed = int(pr.get("additions") or 0) + int(pr.get("deletions") or 0)
    first_review = min(review_times) if review_times else None
    first_approval = min(approval_times) if approval_times else None
    hours_to_merge = hours_between(created_at, merged_at)

    return {
        "month": window.label,
        "repo": repo,
        "pr_number": pr.get("number"),
        "title": pr.get("title") or "",
        "url": pr.get("url") or f"https://github.com/{owner}/{repo}/pull/{pr.get('number')}",
        "author": ((pr.get("author") or {}).get("login")) or "unknown",
        "created_at": created_at.isoformat(),
        "merged_at": merged_at.isoformat(),
        "hours_to_merge": hours_to_merge,
        "hours_to_first_review": hours_between(created_at, first_review),
        "hours_to_first_approval": hours_between(created_at, first_approval),
        "additions": int(pr.get("additions") or 0),
        "deletions": int(pr.get("deletions") or 0),
        "changed_files": int(pr.get("changedFiles") or 0),
        "lines_changed": lines_changed,
        "review_count": len(reviews),
        "approval_count": approval_count,
        "reviewer_count": len(reviewers),
        "large_pr": lines_changed > LARGE_PR_LINES,
        "slow_merge": bool(hours_to_merge is not None and hours_to_merge > SLOW_MERGE_HOURS),
        "no_approval": approval_count == 0,
    }


def collect_merged_pr_rows(config: RunConfig, client: GitHubClient) -> GitHubCollection:
    """Collect merged PR detail rows for the configured owner/repos/date window."""

    accessible_repos: list[str] = []
    inaccessible_repos: list[RepoAccessIssue] = []
    for repo in config.repos:
        is_accessible, canonical_name, reason = client.validate_repo(config.owner, repo)
        if is_accessible:
            accessible_repos.append(canonical_name)
        else:
            inaccessible_repos.append(RepoAccessIssue(repo=canonical_name, reason=reason))

    if not accessible_repos:
        requested = ", ".join(config.repos)
        raise RuntimeError(f"No accessible repos resolved for owner={config.owner}: {requested}")

    rows: list[dict[str, Any]] = []
    for repo in accessible_repos:
        for window in month_windows(config.date_window.start, config.date_window.end):
            for pr in client.search_merged_prs(config.owner, repo, window):
                row = row_from_pr(config.owner, repo, window, pr)
                if row is not None:
                    rows.append(row)

    rows.sort(key=lambda item: (item["month"], item["repo"], item["pr_number"]))
    return GitHubCollection(
        owner=config.owner,
        requested_repos=config.requested_repos,
        repos=tuple(accessible_repos),
        inaccessible_repos=tuple(inaccessible_repos),
        detail_rows=tuple(rows),
    )
