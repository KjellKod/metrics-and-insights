#!/usr/bin/env python3
"""Count merged PRs per month across an entire GitHub organization.

Uses the Search API at org scope and reads ``total_count`` directly, so each
month is one cheap REST call regardless of how many PRs were merged. Backoff
on 429 / secondary-rate-limit responses is delegated to the hardened
``GitHubClient`` from ``git_metrics.ci_maturity_report``.

Examples::

    python -m git_metrics.org_merged_prs_per_month \
        --from 2025-05-01 --to 2026-05-08

    python -m git_metrics.org_merged_prs_per_month \
        --from 2025-01-01 --to 2025-12-31 --format csv > merged_prs.csv
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from dotenv import load_dotenv

from git_metrics.ci_maturity_report import DEFAULT_TOKEN_ENV, GitHubClient, load_token
from git_metrics.throughput_collect import MonthWindow, month_windows


load_dotenv()

ENV_OWNER_KEY = "GITHUB_METRIC_OWNER_OR_ORGANIZATION"
INTER_REQUEST_PAUSE_SECONDS = 0.25
SEARCH_RESULT_CAP = 1000
SEARCH_PAGE_SIZE = 100
GRAPHQL_URL = "https://api.github.com/graphql"
GRAPHQL_PAGE_SIZE = 100

GRAPHQL_LOC_QUERY = """
query($q: String!, $cursor: String) {
  search(type: ISSUE, query: $q, first: 100, after: $cursor) {
    issueCount
    pageInfo { hasNextPage endCursor }
    nodes {
      ... on PullRequest {
        additions
        deletions
      }
    }
  }
}
"""


@dataclass(frozen=True)
class MonthlyMergedCount:
    month: str
    window_start: date
    window_end: date
    merged_prs: int
    per_repo: dict[str, int] | None = None
    additions: int | None = None
    deletions: int | None = None


@dataclass(frozen=True)
class MergedPrReport:
    owner: str
    range_start: date
    range_end: date
    rows: tuple[MonthlyMergedCount, ...]
    rate_limit_events: tuple[dict[str, Any], ...]

    @property
    def total(self) -> int:
        return sum(row.merged_prs for row in self.rows)

    @property
    def has_loc(self) -> bool:
        return any(row.additions is not None or row.deletions is not None for row in self.rows)

    @property
    def total_additions(self) -> int:
        return sum(row.additions or 0 for row in self.rows)

    @property
    def total_deletions(self) -> int:
        return sum(row.deletions or 0 for row in self.rows)


def parse_iso_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Count merged PRs per month across an entire GitHub organization.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--from",
        dest="from_date",
        required=True,
        type=parse_iso_date,
        help="Inclusive start date (YYYY-MM-DD). Example: --from 2025-05-01",
    )
    parser.add_argument(
        "--to",
        dest="to_date",
        required=True,
        type=parse_iso_date,
        help="Inclusive end date (YYYY-MM-DD). Example: --to 2026-05-08",
    )
    parser.add_argument(
        "--owner",
        default=argparse.SUPPRESS,
        help=f"GitHub organization or user. Defaults to ${ENV_OWNER_KEY}.",
    )
    parser.add_argument(
        "--token-env",
        default=DEFAULT_TOKEN_ENV,
        help="Environment variable holding the GitHub token.",
    )
    parser.add_argument(
        "--format",
        choices=["table", "json", "csv"],
        default="table",
        help="Output format.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Also report per-repo merged PR counts per month. Costs extra API calls (paginates search results).",
    )
    parser.add_argument(
        "-l",
        "--loc",
        action="store_true",
        help="Also report total additions and deletions per month. Uses GraphQL search to collect per-PR LOC data.",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging.")
    return parser


def _search_query(owner: str, range_start: date, range_end: date) -> str:
    return f"org:{owner} is:pr is:merged merged:{range_start.isoformat()}..{range_end.isoformat()}"


def count_merged_prs_for_window(
    client: GitHubClient,
    owner: str,
    window: MonthWindow,
) -> int:
    """Return the total merged PR count for ``owner`` within ``window``."""

    payload = client.get_json(
        "/search/issues",
        params={"q": _search_query(owner, window.start, window.end), "per_page": 1},
    )
    return int(payload.get("total_count") or 0)


def per_repo_counts_for_window(
    client: GitHubClient,
    owner: str,
    window: MonthWindow,
) -> tuple[dict[str, int], int]:
    """Return ``({repo: count}, total)`` for merged PRs in ``window``.

    Paginates the Search API. When the window has more than the 1000-result
    Search cap, the window is halved recursively so every PR is attributable.
    """

    return _per_repo_counts_for_range(client, owner, window.start, window.end)


def _per_repo_counts_for_range(
    client: GitHubClient,
    owner: str,
    range_start: date,
    range_end: date,
) -> tuple[dict[str, int], int]:
    query = _search_query(owner, range_start, range_end)
    head = client.get_json("/search/issues", params={"q": query, "per_page": 1})
    total = int(head.get("total_count") or 0)

    if total > SEARCH_RESULT_CAP:
        if range_start >= range_end:
            raise RuntimeError(
                f"GitHub search returned more than {SEARCH_RESULT_CAP} merged PRs for "
                f"org:{owner} on {range_start.isoformat()}; cannot disambiguate per repo"
            )
        midpoint = range_start + timedelta(days=(range_end - range_start).days // 2)
        left_counts, left_total = _per_repo_counts_for_range(client, owner, range_start, midpoint)
        right_counts, right_total = _per_repo_counts_for_range(client, owner, midpoint + timedelta(days=1), range_end)
        merged: dict[str, int] = dict(left_counts)
        for repo, count in right_counts.items():
            merged[repo] = merged.get(repo, 0) + count
        return merged, left_total + right_total

    counts: dict[str, int] = {}
    if total == 0:
        return counts, 0

    page = 1
    max_pages = (SEARCH_RESULT_CAP // SEARCH_PAGE_SIZE) + 1
    while page <= max_pages:
        payload = client.get_json(
            "/search/issues",
            params={"q": query, "per_page": SEARCH_PAGE_SIZE, "page": page},
        )
        items = payload.get("items") or []
        for item in items:
            repo_url = item.get("repository_url") or ""
            repo_name = repo_url.rsplit("/", 1)[-1] if repo_url else ""
            if not repo_name:
                continue
            counts[repo_name] = counts.get(repo_name, 0) + 1
        if len(items) < SEARCH_PAGE_SIZE:
            break
        page += 1
    return counts, total


def _graphql(client: GitHubClient, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    """POST to GraphQL, reusing the REST client's session and rate-limit backoff.

    GitHub returns GraphQL rate-limit errors as HTTP 200 with an ``errors`` field,
    so we have to detect them in the JSON payload too — not just via status codes.
    """

    for attempt in range(1, client.max_retries + 1):
        response = client.session.post(
            GRAPHQL_URL,
            json={"query": query, "variables": variables},
            timeout=60,
        )
        if client._should_wait_for_rate_limit(response):
            if attempt == client.max_retries:
                response.raise_for_status()
            client._wait_for_rate_limit(response, GRAPHQL_URL)
            continue

        response.raise_for_status()
        payload = response.json()
        if "errors" in payload:
            messages = "; ".join(error.get("message", "unknown error") for error in payload["errors"])
            if attempt < client.max_retries and "rate limit" in messages.lower():
                client._wait_for_rate_limit(response, GRAPHQL_URL)
                continue
            raise RuntimeError(f"GraphQL error: {messages}")
        return payload["data"]

    raise RuntimeError(f"GraphQL request failed after {client.max_retries} attempts")


def loc_for_window(
    client: GitHubClient,
    owner: str,
    window: MonthWindow,
) -> tuple[int, int, int]:
    """Return ``(additions, deletions, total_count)`` for merged PRs in ``window``.

    Uses GraphQL search so that additions/deletions arrive in the same page as the
    PR identity. Halves the window recursively if the result set exceeds the
    1000-result Search cap.
    """

    return _loc_for_range(client, owner, window.start, window.end)


def _loc_for_range(
    client: GitHubClient,
    owner: str,
    range_start: date,
    range_end: date,
) -> tuple[int, int, int]:
    query_text = _search_query(owner, range_start, range_end)
    cursor: str | None = None
    additions = 0
    deletions = 0
    total = 0
    first_page = True

    while True:
        data = _graphql(client, GRAPHQL_LOC_QUERY, {"q": query_text, "cursor": cursor})
        search = data["search"]
        if first_page:
            total = int(search.get("issueCount") or 0)
            if total > SEARCH_RESULT_CAP:
                if range_start >= range_end:
                    raise RuntimeError(
                        f"GitHub search returned more than {SEARCH_RESULT_CAP} merged PRs for "
                        f"org:{owner} on {range_start.isoformat()}; cannot collect LOC accurately"
                    )
                midpoint = range_start + timedelta(days=(range_end - range_start).days // 2)
                left_add, left_del, left_total = _loc_for_range(client, owner, range_start, midpoint)
                right_add, right_del, right_total = _loc_for_range(
                    client, owner, midpoint + timedelta(days=1), range_end
                )
                return left_add + right_add, left_del + right_del, left_total + right_total
            first_page = False

        for node in search.get("nodes") or []:
            if not node:
                continue
            additions += int(node.get("additions") or 0)
            deletions += int(node.get("deletions") or 0)

        page_info = search.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")

    return additions, deletions, total


def collect_report(
    client: GitHubClient,
    owner: str,
    range_start: date,
    range_end: date,
    *,
    verbose: bool = False,
    loc: bool = False,
    sleep_fn: Any = time.sleep,
    pause_seconds: float = INTER_REQUEST_PAUSE_SECONDS,
) -> MergedPrReport:
    if range_end < range_start:
        raise ValueError("--to must be on or after --from")

    rows: list[MonthlyMergedCount] = []
    windows = month_windows(range_start, range_end)
    for index, window in enumerate(windows):
        if index > 0 and pause_seconds > 0:
            sleep_fn(pause_seconds)
        if verbose:
            per_repo, count = per_repo_counts_for_window(client, owner, window)
        else:
            per_repo = None
            count = count_merged_prs_for_window(client, owner, window)
        additions: int | None = None
        deletions: int | None = None
        if loc:
            if pause_seconds > 0:
                sleep_fn(pause_seconds)
            additions, deletions, _loc_total = loc_for_window(client, owner, window)
        rows.append(
            MonthlyMergedCount(
                month=window.label,
                window_start=window.start,
                window_end=window.end,
                merged_prs=count,
                per_repo=per_repo,
                additions=additions,
                deletions=deletions,
            )
        )

    rate_limit_events = tuple(
        {
            "url": event.url,
            "status_code": event.status_code,
            "slept_seconds": event.slept_seconds,
            "reset_at": event.reset_at,
        }
        for event in client.rate_limit_events
    )
    return MergedPrReport(
        owner=owner,
        range_start=range_start,
        range_end=range_end,
        rows=tuple(rows),
        rate_limit_events=rate_limit_events,
    )


def _render_per_repo_block(report: MergedPrReport) -> list[str]:
    lines: list[str] = ["Per-repo merged PRs (verbose)"]
    for row in report.rows:
        if row.per_repo is None:
            continue
        lines.append(f"{row.month}  ({row.merged_prs:,} total)")
        if not row.per_repo:
            lines.append("  (no merged PRs)")
            continue
        ranked = sorted(row.per_repo.items(), key=lambda item: (-item[1], item[0]))
        repo_width = max(len(repo) for repo, _ in ranked)
        for repo, count in ranked:
            lines.append(f"  {repo:<{repo_width}}  {count:>6,}")
    lines.append("")
    return lines


def render_table(report: MergedPrReport) -> str:
    header = (
        f"Org: {report.owner}  |  Window: "
        f"{report.range_start.isoformat()} .. {report.range_end.isoformat()}  |  "
        "Visibility: token-scoped (private repos included if the token can see them)"
    )
    lines: list[str] = []
    if any(row.per_repo is not None for row in report.rows):
        lines.extend(_render_per_repo_block(report))
    lines.append(header)
    lines.append("")
    if report.has_loc:
        lines.append(f"{'month':<10}{'merged_prs':>12}{'additions':>14}{'deletions':>14}")
        for row in report.rows:
            lines.append(
                f"{row.month:<10}{row.merged_prs:>12,}" f"{(row.additions or 0):>14,}" f"{(row.deletions or 0):>14,}"
            )
        lines.append(
            f"{'TOTAL':<10}{report.total:>12,}" f"{report.total_additions:>14,}" f"{report.total_deletions:>14,}"
        )
    else:
        lines.append(f"{'month':<10}{'merged_prs':>12}")
        for row in report.rows:
            lines.append(f"{row.month:<10}{row.merged_prs:>12,}")
        lines.append(f"{'TOTAL':<10}{report.total:>12,}")
    if report.rate_limit_events:
        lines.append("")
        lines.append(f"rate_limit_events: {len(report.rate_limit_events)}")
    return "\n".join(lines)


def render_json(report: MergedPrReport) -> str:
    rows_payload: list[dict[str, Any]] = []
    for row in report.rows:
        item: dict[str, Any] = {
            "month": row.month,
            "window_start": row.window_start.isoformat(),
            "window_end": row.window_end.isoformat(),
            "merged_prs": row.merged_prs,
        }
        if row.additions is not None:
            item["additions"] = row.additions
        if row.deletions is not None:
            item["deletions"] = row.deletions
        if row.per_repo is not None:
            item["per_repo"] = dict(sorted(row.per_repo.items(), key=lambda kv: (-kv[1], kv[0])))
        rows_payload.append(item)
    payload: dict[str, Any] = {
        "owner": report.owner,
        "from": report.range_start.isoformat(),
        "to": report.range_end.isoformat(),
        "rows": rows_payload,
        "total": report.total,
        "rate_limit_events": list(report.rate_limit_events),
    }
    if report.has_loc:
        payload["total_additions"] = report.total_additions
        payload["total_deletions"] = report.total_deletions
    return json.dumps(payload, indent=2)


def render_csv(report: MergedPrReport) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    has_per_repo = any(row.per_repo is not None for row in report.rows)
    if has_per_repo:
        writer.writerow(["month", "repo", "merged_prs"])
        for row in report.rows:
            if row.per_repo is None:
                continue
            for repo, count in sorted(row.per_repo.items(), key=lambda kv: (-kv[1], kv[0])):
                writer.writerow([row.month, repo, count])
            writer.writerow([row.month, "(month total)", row.merged_prs])
        writer.writerow(["TOTAL", "", report.total])
    elif report.has_loc:
        writer.writerow(["month", "window_start", "window_end", "merged_prs", "additions", "deletions"])
        for row in report.rows:
            writer.writerow(
                [
                    row.month,
                    row.window_start.isoformat(),
                    row.window_end.isoformat(),
                    row.merged_prs,
                    row.additions or 0,
                    row.deletions or 0,
                ]
            )
        writer.writerow(["TOTAL", "", "", report.total, report.total_additions, report.total_deletions])
    else:
        writer.writerow(["month", "window_start", "window_end", "merged_prs"])
        for row in report.rows:
            writer.writerow([row.month, row.window_start.isoformat(), row.window_end.isoformat(), row.merged_prs])
        writer.writerow(["TOTAL", "", "", report.total])
    return buffer.getvalue().rstrip("\n")


def render_report(report: MergedPrReport, output_format: str) -> str:
    if output_format == "json":
        return render_json(report)
    if output_format == "csv":
        return render_csv(report)
    return render_table(report)


def main() -> None:
    parser = build_argument_parser()
    args = parser.parse_args()

    if not getattr(args, "owner", None):
        args.owner = os.getenv(ENV_OWNER_KEY)
    if not args.owner:
        parser.error(f"GitHub owner missing. Provide --owner or set {ENV_OWNER_KEY}.")

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        token = load_token(args.token_env)
        client = GitHubClient(token, auth_source=f"env:{args.token_env}")
        report = collect_report(client, args.owner, args.from_date, args.to_date, verbose=args.verbose, loc=args.loc)
        print(render_report(report, args.format))
    except Exception as exc:  # pylint: disable=broad-except
        logging.getLogger(__name__).error("%s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
