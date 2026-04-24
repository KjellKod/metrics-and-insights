from __future__ import annotations

import re
from datetime import date

import pytest

from git_metrics.throughput_collect import GitHubClient, MonthWindow


class StubGitHubClient(GitHubClient):
    def __init__(self, payloads: dict[tuple[str, str, str | None], dict]) -> None:
        super().__init__("test-token")
        self.payloads = payloads
        self.queries: list[tuple[str, str]] = []

    def graphql(self, query: str, variables: dict[str, object]) -> dict:
        match = re.search(r"merged:(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})", str(variables["query"]))
        if match is None:
            raise AssertionError(f"missing merged range in query: {variables['query']!r}")
        key = (match.group(1), match.group(2), variables.get("cursor"))
        self.queries.append((match.group(1), match.group(2)))
        payload = self.payloads.get(key)
        if payload is None:
            raise AssertionError(f"unexpected GraphQL request for {key}")
        return {"search": payload}


def _search_payload(issue_count: int, numbers: list[int], *, has_next_page: bool = False, end_cursor: str | None = None) -> dict:
    return {
        "issueCount": issue_count,
        "pageInfo": {"hasNextPage": has_next_page, "endCursor": end_cursor},
        "nodes": [{"number": number} for number in numbers],
    }


def test_search_merged_prs_splits_large_windows_before_hitting_github_limit() -> None:
    client = StubGitHubClient(
        {
            ("2026-02-01", "2026-02-04", None): _search_payload(1200, []),
            ("2026-02-01", "2026-02-02", None): _search_payload(2, [11, 12]),
            ("2026-02-03", "2026-02-04", None): _search_payload(1, [13]),
        }
    )
    window = MonthWindow(label="2026-02", start=date(2026, 2, 1), end=date(2026, 2, 4))

    rows = client.search_merged_prs("example-org", "example-repo", window)

    assert [row["number"] for row in rows] == [11, 12, 13]
    assert ("2026-02-01", "2026-02-04") in client.queries
    assert ("2026-02-01", "2026-02-02") in client.queries
    assert ("2026-02-03", "2026-02-04") in client.queries


def test_search_merged_prs_raises_when_single_day_window_still_exceeds_limit() -> None:
    client = StubGitHubClient(
        {
            ("2026-02-01", "2026-02-01", None): _search_payload(1001, []),
        }
    )
    window = MonthWindow(label="2026-02", start=date(2026, 2, 1), end=date(2026, 2, 1))

    with pytest.raises(RuntimeError, match="more than 1000 merged PRs"):
        client.search_merged_prs("example-org", "example-repo", window)
