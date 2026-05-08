from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import requests

from git_metrics.ci_maturity_report import GitHubClient
from git_metrics.org_merged_prs_per_month import (
    build_argument_parser,
    collect_report,
    count_merged_prs_for_window,
    loc_for_window,
    per_repo_counts_for_window,
    render_csv,
    render_json,
    render_table,
)
from git_metrics.throughput_collect import MonthWindow, month_windows


class _StubResponse:
    def __init__(self, status_code: int, payload: dict[str, Any] | None = None, headers: dict[str, str] | None = None):
        self.status_code = status_code
        self.reason = "OK" if status_code == 200 else "ERR"
        self._payload = payload or {}
        self.headers = headers or {}
        self.text = json.dumps(self._payload)

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)


class _RecordingSession:
    """Stand-in for requests.Session that returns scripted responses."""

    def __init__(self, responses: list[_StubResponse]):
        self._responses = list(responses)
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        self.post_calls: list[tuple[str, dict[str, Any] | None]] = []
        self.headers: dict[str, str] = {}

    def get(self, url: str, *, params: dict[str, Any] | None = None, timeout: float = 0) -> _StubResponse:
        self.calls.append((url, dict(params) if params is not None else None))
        if not self._responses:
            raise AssertionError("no scripted responses left")
        return self._responses.pop(0)

    def post(self, url: str, *, json: dict[str, Any] | None = None, timeout: float = 0) -> _StubResponse:
        self.post_calls.append((url, dict(json) if json is not None else None))
        if not self._responses:
            raise AssertionError("no scripted responses left")
        return self._responses.pop(0)


def _make_client(responses: list[_StubResponse]) -> tuple[GitHubClient, _RecordingSession, list[float]]:
    sleeps: list[float] = []
    client = GitHubClient("token", sleep_fn=sleeps.append)
    session = _RecordingSession(responses)
    client.session = session  # type: ignore[assignment]
    return client, session, sleeps


def test_count_merged_prs_for_window_builds_search_query_and_extracts_total_count() -> None:
    client, session, _sleeps = _make_client([_StubResponse(200, {"total_count": 142, "incomplete_results": False})])
    window = MonthWindow(label="2025-05", start=date(2025, 5, 1), end=date(2025, 5, 31))

    count = count_merged_prs_for_window(client, "onfleet", window)

    assert count == 142
    assert len(session.calls) == 1
    url, params = session.calls[0]
    assert url == "https://api.github.com/search/issues"
    assert params == {
        "q": "org:onfleet is:pr is:merged merged:2025-05-01..2025-05-31",
        "per_page": 1,
    }


def test_count_merged_prs_handles_missing_total_count_as_zero() -> None:
    client, _session, _sleeps = _make_client([_StubResponse(200, {"incomplete_results": False})])
    window = MonthWindow(label="2025-05", start=date(2025, 5, 1), end=date(2025, 5, 31))

    assert count_merged_prs_for_window(client, "onfleet", window) == 0


def test_collect_report_iterates_month_windows_and_paces_requests() -> None:
    responses = [
        _StubResponse(200, {"total_count": 10}),
        _StubResponse(200, {"total_count": 22}),
        _StubResponse(200, {"total_count": 5}),
    ]
    client, session, sleeps = _make_client(responses)

    report = collect_report(
        client,
        "onfleet",
        date(2025, 3, 15),
        date(2025, 5, 8),
        sleep_fn=sleeps.append,
        pause_seconds=0.1,
    )

    # 3 windows: partial March, full April, partial May (clamped by month_windows)
    assert [row.month for row in report.rows] == ["2025-03", "2025-04", "2025-05"]
    assert [row.merged_prs for row in report.rows] == [10, 22, 5]
    assert report.total == 37
    assert report.rows[0].window_start == date(2025, 3, 15)
    assert report.rows[-1].window_end == date(2025, 5, 8)
    # Pacing pauses fire between calls only (N-1 pauses).
    assert sleeps == [0.1, 0.1]
    # Each call hits search/issues with the right per-window query string.
    assert all(call[0] == "https://api.github.com/search/issues" for call in session.calls)
    assert session.calls[0][1] == {
        "q": "org:onfleet is:pr is:merged merged:2025-03-15..2025-03-31",
        "per_page": 1,
    }
    assert session.calls[1][1] == {
        "q": "org:onfleet is:pr is:merged merged:2025-04-01..2025-04-30",
        "per_page": 1,
    }
    assert session.calls[2][1] == {
        "q": "org:onfleet is:pr is:merged merged:2025-05-01..2025-05-08",
        "per_page": 1,
    }


def test_collect_report_retries_after_secondary_rate_limit() -> None:
    rate_limited = _StubResponse(
        403,
        {"message": "API rate limit exceeded"},
        headers={"Retry-After": "1"},
    )
    rate_limited.text = "API rate limit exceeded"
    responses = [rate_limited, _StubResponse(200, {"total_count": 7})]
    client, _session, sleeps = _make_client(responses)
    window = MonthWindow(label="2025-05", start=date(2025, 5, 1), end=date(2025, 5, 31))

    count = count_merged_prs_for_window(client, "onfleet", window)

    assert count == 7
    assert sleeps == [1.0]
    assert len(client.rate_limit_events) == 1
    assert client.rate_limit_events[0].slept_seconds == 1.0


def test_collect_report_rejects_inverted_range() -> None:
    client, _session, _sleeps = _make_client([])
    with pytest.raises(ValueError):
        collect_report(client, "onfleet", date(2025, 6, 1), date(2025, 5, 1), sleep_fn=lambda _s: None)


def test_collect_report_rejects_future_end_date() -> None:
    client, _session, _sleeps = _make_client([])
    with pytest.raises(ValueError, match="future"):
        collect_report(
            client,
            "onfleet",
            date(2026, 5, 1),
            date(2026, 6, 1),
            today=date(2026, 5, 8),
            sleep_fn=lambda _s: None,
        )


def _sample_report():
    return collect_report(
        *_make_collect_inputs(),
        sleep_fn=lambda _s: None,
        pause_seconds=0,
    )


def _make_collect_inputs():
    responses = [
        _StubResponse(200, {"total_count": 100}),
        _StubResponse(200, {"total_count": 250}),
    ]
    client, _session, _sleeps = _make_client(responses)
    return client, "onfleet", date(2025, 4, 1), date(2025, 5, 31)


def test_render_table_shows_per_month_rows_and_total() -> None:
    report = _sample_report()
    rendered = render_table(report)
    assert "Org: onfleet" in rendered
    assert "Window: 2025-04-01 .. 2025-05-31" in rendered
    lines = {line.split()[0]: line for line in rendered.splitlines() if line and line.split()}
    assert lines["2025-04"].split() == ["2025-04", "100"]
    assert lines["2025-05"].split() == ["2025-05", "250"]
    assert lines["TOTAL"].split() == ["TOTAL", "350"]


def test_render_json_serializes_full_payload() -> None:
    report = _sample_report()
    payload = json.loads(render_json(report))
    assert payload["owner"] == "onfleet"
    assert payload["from"] == "2025-04-01"
    assert payload["to"] == "2025-05-31"
    assert payload["total"] == 350
    assert payload["rows"][0] == {
        "month": "2025-04",
        "window_start": "2025-04-01",
        "window_end": "2025-04-30",
        "merged_prs": 100,
    }
    assert payload["rate_limit_events"] == []


def test_render_csv_emits_header_rows_and_total() -> None:
    report = _sample_report()
    rendered = render_csv(report)
    assert rendered.splitlines()[0] == "month,window_start,window_end,merged_prs"
    assert rendered.splitlines()[1] == "2025-04,2025-04-01,2025-04-30,100"
    assert rendered.splitlines()[2] == "2025-05,2025-05-01,2025-05-31,250"
    assert rendered.splitlines()[-1] == "TOTAL,,,350"


def test_argument_parser_requires_from_and_to_and_defaults_format_to_table() -> None:
    parser = build_argument_parser()
    args = parser.parse_args(["--from", "2025-01-01", "--to", "2025-12-31"])
    assert args.from_date == date(2025, 1, 1)
    assert args.to_date == date(2025, 12, 31)
    assert args.format == "table"
    assert args.token_env == "GITHUB_TOKEN_READONLY_WEB"
    assert not hasattr(args, "owner")  # SUPPRESS keeps it absent until env fallback


def _items_payload(repos: list[str], total: int | None = None) -> dict[str, Any]:
    items = [{"repository_url": f"https://api.github.com/repos/onfleet/{name}"} for name in repos]
    return {"total_count": total if total is not None else len(repos), "items": items}


def test_per_repo_counts_paginates_and_aggregates_by_repo() -> None:
    page_one_repos = ["api"] * 60 + ["web"] * 40  # 100 items -> next page expected
    page_two_repos = ["api"] * 5 + ["docs"] * 3  # < 100 items -> stop
    responses = [
        _StubResponse(200, {"total_count": 108, "items": []}),  # head probe (per_page=1)
        _StubResponse(200, _items_payload(page_one_repos, total=108)),
        _StubResponse(200, _items_payload(page_two_repos, total=108)),
    ]
    client, session, _sleeps = _make_client(responses)
    window = MonthWindow(label="2025-05", start=date(2025, 5, 1), end=date(2025, 5, 31))

    counts, total = per_repo_counts_for_window(client, "onfleet", window)

    assert total == 108
    assert counts == {"api": 65, "web": 40, "docs": 3}
    # First call is the head probe with per_page=1; subsequent calls paginate at 100/page.
    assert session.calls[0][1]["per_page"] == 1
    assert session.calls[1][1]["per_page"] == 100
    assert session.calls[1][1]["page"] == 1
    assert session.calls[2][1]["page"] == 2


def test_per_repo_counts_stops_at_page_10_when_total_equals_search_cap() -> None:
    # GitHub Search caps at page 10 (1000 results); page 11 returns 422.
    # When total == 1000 exactly, the loop must terminate after page 10
    # without attempting page 11.
    full_page = _items_payload(["api"] * 100, total=1000)
    responses = [_StubResponse(200, {"total_count": 1000, "items": []})]  # head
    responses.extend(_StubResponse(200, full_page) for _ in range(10))
    client, session, _sleeps = _make_client(responses)
    window = MonthWindow(label="2025-05", start=date(2025, 5, 1), end=date(2025, 5, 31))

    counts, total = per_repo_counts_for_window(client, "onfleet", window)

    assert total == 1000
    assert counts == {"api": 1000}
    # 1 head probe + 10 paginated calls = 11 total. No page 11 requested.
    assert len(session.calls) == 11
    pages_requested = [params.get("page") for _url, params in session.calls if params and params.get("page")]
    assert pages_requested == list(range(1, 11))


def test_per_repo_counts_halves_window_when_total_exceeds_search_cap() -> None:
    # >1000-result window forces a recursive split. Each half returns <100 items
    # so pagination terminates cleanly and we can assert on the merged result.
    responses = [
        _StubResponse(200, {"total_count": 1500, "items": []}),  # head: too big -> split
        _StubResponse(200, {"total_count": 700, "items": []}),  # left half head
        _StubResponse(200, _items_payload(["api", "api", "web"], total=700)),
        _StubResponse(200, {"total_count": 800, "items": []}),  # right half head
        _StubResponse(200, _items_payload(["web", "docs"], total=800)),
    ]
    client, session, _sleeps = _make_client(responses)
    window = MonthWindow(label="2025-05", start=date(2025, 5, 1), end=date(2025, 5, 31))

    counts, total = per_repo_counts_for_window(client, "onfleet", window)

    # Total preserved from per-half head probes.
    assert total == 700 + 800
    # Per-repo counts merged across halves.
    assert counts == {"api": 2, "web": 2, "docs": 1}
    # Three head probes (full window + 2 halves) confirms the recursive split fired.
    head_calls = [params for _url, params in session.calls if params and params.get("per_page") == 1]
    assert len(head_calls) == 3


def test_collect_report_in_verbose_mode_attaches_per_repo_counts() -> None:
    responses = [
        # April: head + one page
        _StubResponse(200, {"total_count": 3, "items": []}),
        _StubResponse(200, _items_payload(["api", "api", "web"], total=3)),
        # May: head + one page
        _StubResponse(200, {"total_count": 2, "items": []}),
        _StubResponse(200, _items_payload(["api", "docs"], total=2)),
    ]
    client, _session, _sleeps = _make_client(responses)

    report = collect_report(
        client,
        "onfleet",
        date(2025, 4, 1),
        date(2025, 5, 31),
        verbose=True,
        sleep_fn=lambda _s: None,
        pause_seconds=0,
    )

    assert [row.merged_prs for row in report.rows] == [3, 2]
    assert report.rows[0].per_repo == {"api": 2, "web": 1}
    assert report.rows[1].per_repo == {"api": 1, "docs": 1}
    assert report.total == 5


def test_render_table_in_verbose_mode_shows_per_repo_block_above_totals() -> None:
    responses = [
        _StubResponse(200, {"total_count": 3, "items": []}),
        _StubResponse(200, _items_payload(["api", "api", "web"], total=3)),
    ]
    client, _session, _sleeps = _make_client(responses)
    report = collect_report(
        client,
        "onfleet",
        date(2025, 4, 1),
        date(2025, 4, 30),
        verbose=True,
        sleep_fn=lambda _s: None,
        pause_seconds=0,
    )
    rendered = render_table(report)
    breakdown_index = rendered.find("Per-repo merged PRs")
    totals_header_index = rendered.find("Org: onfleet")
    assert breakdown_index != -1
    assert totals_header_index != -1
    assert breakdown_index < totals_header_index
    assert "2025-04  (3 total)" in rendered
    # Repos sorted by count desc, then name.
    api_index = rendered.find("api")
    web_index = rendered.find("web")
    assert api_index < web_index


def test_render_json_in_verbose_mode_includes_per_repo_object() -> None:
    responses = [
        _StubResponse(200, {"total_count": 3, "items": []}),
        _StubResponse(200, _items_payload(["api", "api", "web"], total=3)),
    ]
    client, _session, _sleeps = _make_client(responses)
    report = collect_report(
        client,
        "onfleet",
        date(2025, 4, 1),
        date(2025, 4, 30),
        verbose=True,
        sleep_fn=lambda _s: None,
        pause_seconds=0,
    )
    payload = json.loads(render_json(report))
    assert payload["rows"][0]["per_repo"] == {"api": 2, "web": 1}


def test_render_csv_in_verbose_mode_emits_per_repo_rows() -> None:
    responses = [
        _StubResponse(200, {"total_count": 3, "items": []}),
        _StubResponse(200, _items_payload(["api", "api", "web"], total=3)),
    ]
    client, _session, _sleeps = _make_client(responses)
    report = collect_report(
        client,
        "onfleet",
        date(2025, 4, 1),
        date(2025, 4, 30),
        verbose=True,
        sleep_fn=lambda _s: None,
        pause_seconds=0,
    )
    rendered = render_csv(report)
    lines = rendered.splitlines()
    assert lines[0] == "month,repo,merged_prs"
    assert lines[1] == "2025-04,api,2"
    assert lines[2] == "2025-04,web,1"
    assert lines[3] == "2025-04,(month total),3"
    assert lines[-1] == "TOTAL,,3"


def test_argument_parser_accepts_short_v_flag() -> None:
    parser = build_argument_parser()
    args = parser.parse_args(["--from", "2025-01-01", "--to", "2025-12-31", "-v"])
    assert args.verbose is True
    args_default = parser.parse_args(["--from", "2025-01-01", "--to", "2025-12-31"])
    assert args_default.verbose is False


def _graphql_response(*, total: int, nodes: list[dict[str, int]], next_cursor: str | None = None) -> _StubResponse:
    return _StubResponse(
        200,
        {
            "data": {
                "search": {
                    "issueCount": total,
                    "pageInfo": {
                        "hasNextPage": bool(next_cursor),
                        "endCursor": next_cursor,
                    },
                    "nodes": nodes,
                }
            }
        },
    )


def test_loc_for_window_sums_additions_and_deletions_across_pages() -> None:
    responses = [
        _graphql_response(
            total=3,
            nodes=[
                {"additions": 100, "deletions": 30},
                {"additions": 50, "deletions": 20},
            ],
            next_cursor="abc",
        ),
        _graphql_response(
            total=3,
            nodes=[
                {"additions": 7, "deletions": 1},
            ],
        ),
    ]
    client, session, _sleeps = _make_client(responses)
    window = MonthWindow(label="2025-04", start=date(2025, 4, 1), end=date(2025, 4, 30))

    additions, deletions, total = loc_for_window(client, "onfleet", window)

    assert (additions, deletions, total) == (157, 51, 3)
    # GraphQL POSTs only — no REST GETs from this path.
    assert len(session.post_calls) == 2
    assert len(session.calls) == 0
    first_payload = session.post_calls[0][1]
    assert first_payload is not None
    assert "query" in first_payload and "search" in first_payload["query"]
    assert first_payload["variables"]["q"] == "org:onfleet is:pr is:merged merged:2025-04-01..2025-04-30"
    assert first_payload["variables"]["cursor"] is None
    # Second page passes the cursor returned by the first.
    assert session.post_calls[1][1]["variables"]["cursor"] == "abc"


def test_loc_for_window_halves_window_when_total_exceeds_search_cap() -> None:
    responses = [
        _graphql_response(total=1500, nodes=[]),  # head -> too big -> split
        _graphql_response(  # left half
            total=700,
            nodes=[{"additions": 200, "deletions": 80}],
        ),
        _graphql_response(  # right half
            total=800,
            nodes=[{"additions": 300, "deletions": 50}],
        ),
    ]
    client, _session, _sleeps = _make_client(responses)
    window = MonthWindow(label="2025-04", start=date(2025, 4, 1), end=date(2025, 4, 30))

    additions, deletions, total = loc_for_window(client, "onfleet", window)

    assert additions == 500
    assert deletions == 130
    assert total == 1500


def test_collect_report_in_loc_mode_attaches_additions_and_deletions() -> None:
    responses = [
        # Apr: count head, then graphql
        _StubResponse(200, {"total_count": 2}),
        _graphql_response(total=2, nodes=[{"additions": 100, "deletions": 30}, {"additions": 50, "deletions": 20}]),
        # May: count head, then graphql
        _StubResponse(200, {"total_count": 1}),
        _graphql_response(total=1, nodes=[{"additions": 9, "deletions": 4}]),
    ]
    client, _session, _sleeps = _make_client(responses)

    report = collect_report(
        client,
        "onfleet",
        date(2025, 4, 1),
        date(2025, 5, 31),
        loc=True,
        sleep_fn=lambda _s: None,
        pause_seconds=0,
    )

    assert [row.merged_prs for row in report.rows] == [2, 1]
    assert [row.additions for row in report.rows] == [150, 9]
    assert [row.deletions for row in report.rows] == [50, 4]
    assert report.total == 3
    assert report.total_additions == 159
    assert report.total_deletions == 54
    assert report.has_loc is True


def test_render_table_in_loc_mode_includes_additions_and_deletions_columns() -> None:
    responses = [
        _StubResponse(200, {"total_count": 2}),
        _graphql_response(total=2, nodes=[{"additions": 100, "deletions": 30}, {"additions": 50, "deletions": 20}]),
    ]
    client, _session, _sleeps = _make_client(responses)
    report = collect_report(
        client,
        "onfleet",
        date(2025, 4, 1),
        date(2025, 4, 30),
        loc=True,
        sleep_fn=lambda _s: None,
        pause_seconds=0,
    )
    rendered = render_table(report)
    header_line = [line for line in rendered.splitlines() if "merged_prs" in line][0]
    assert "additions" in header_line
    assert "deletions" in header_line
    apr_row = [line for line in rendered.splitlines() if line.startswith("2025-04")][0]
    cells = apr_row.split()
    assert cells[0] == "2025-04"
    assert cells[1] == "2"
    assert cells[2] == "150"
    assert cells[3] == "50"
    total_row = [line for line in rendered.splitlines() if line.startswith("TOTAL")][0]
    assert total_row.split() == ["TOTAL", "2", "150", "50"]


def test_render_json_in_loc_mode_includes_additions_deletions_and_totals() -> None:
    responses = [
        _StubResponse(200, {"total_count": 2}),
        _graphql_response(total=2, nodes=[{"additions": 100, "deletions": 30}, {"additions": 50, "deletions": 20}]),
    ]
    client, _session, _sleeps = _make_client(responses)
    report = collect_report(
        client,
        "onfleet",
        date(2025, 4, 1),
        date(2025, 4, 30),
        loc=True,
        sleep_fn=lambda _s: None,
        pause_seconds=0,
    )
    payload = json.loads(render_json(report))
    assert payload["rows"][0]["additions"] == 150
    assert payload["rows"][0]["deletions"] == 50
    assert payload["total_additions"] == 150
    assert payload["total_deletions"] == 50


def test_render_csv_in_loc_mode_emits_extra_columns() -> None:
    responses = [
        _StubResponse(200, {"total_count": 2}),
        _graphql_response(total=2, nodes=[{"additions": 100, "deletions": 30}, {"additions": 50, "deletions": 20}]),
    ]
    client, _session, _sleeps = _make_client(responses)
    report = collect_report(
        client,
        "onfleet",
        date(2025, 4, 1),
        date(2025, 4, 30),
        loc=True,
        sleep_fn=lambda _s: None,
        pause_seconds=0,
    )
    rendered = render_csv(report)
    lines = rendered.splitlines()
    assert lines[0] == "month,window_start,window_end,merged_prs,additions,deletions"
    assert lines[1] == "2025-04,2025-04-01,2025-04-30,2,150,50"
    assert lines[-1] == "TOTAL,,,2,150,50"


def test_loc_for_window_retries_when_graphql_returns_200_with_rate_limit_error() -> None:
    rate_limited = _StubResponse(
        200,
        {"errors": [{"message": "API rate limit exceeded for user"}]},
        headers={"Retry-After": "1"},
    )
    success = _graphql_response(total=1, nodes=[{"additions": 5, "deletions": 2}])
    client, _session, sleeps = _make_client([rate_limited, success])
    window = MonthWindow(label="2025-04", start=date(2025, 4, 1), end=date(2025, 4, 30))

    additions, deletions, total = loc_for_window(client, "onfleet", window)

    assert (additions, deletions, total) == (5, 2, 1)
    assert sleeps == [1.0]
    assert len(client.rate_limit_events) == 1


def test_render_csv_in_verbose_plus_loc_mode_includes_per_repo_and_loc_columns() -> None:
    responses = [
        # Verbose path: head + page-1 with 3 items
        _StubResponse(200, {"total_count": 3, "items": []}),
        _StubResponse(200, _items_payload(["api", "api", "web"], total=3)),
        # LOC path: GraphQL with 3 PRs
        _graphql_response(
            total=3,
            nodes=[
                {"additions": 100, "deletions": 30},
                {"additions": 50, "deletions": 20},
                {"additions": 7, "deletions": 1},
            ],
        ),
    ]
    client, _session, _sleeps = _make_client(responses)
    report = collect_report(
        client,
        "onfleet",
        date(2025, 4, 1),
        date(2025, 4, 30),
        verbose=True,
        loc=True,
        sleep_fn=lambda _s: None,
        pause_seconds=0,
    )
    rendered = render_csv(report)
    lines = rendered.splitlines()
    assert lines[0] == "month,repo,merged_prs,additions,deletions"
    # Per-repo rows leave additions/deletions blank (per-repo LOC not collected in v1).
    assert lines[1] == "2025-04,api,2,,"
    assert lines[2] == "2025-04,web,1,,"
    # Per-month total carries the LOC totals.
    assert lines[3] == "2025-04,(month total),3,157,51"
    assert lines[-1] == "TOTAL,,3,157,51"


def test_argument_parser_accepts_short_l_flag() -> None:
    parser = build_argument_parser()
    args = parser.parse_args(["--from", "2025-01-01", "--to", "2025-12-31", "-l"])
    assert args.loc is True
    args_default = parser.parse_args(["--from", "2025-01-01", "--to", "2025-12-31"])
    assert args_default.loc is False


def test_script_path_help_explains_module_invocation_and_verbose_flag() -> None:
    repo_root = Path(__file__).resolve().parents[3]

    result = subprocess.run(
        [sys.executable, "git_metrics/org_merged_prs_per_month.py", "--help"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "python3 -m git_metrics.org_merged_prs_per_month" in result.stdout
    assert "Use -v or --verbose, not --v." in result.stdout


def test_month_windows_sanity_check_for_year_boundaries() -> None:
    # Guard against off-by-one when the range spans Dec/Jan.
    windows = month_windows(date(2024, 12, 15), date(2025, 1, 5))
    assert [w.label for w in windows] == ["2024-12", "2025-01"]
    assert windows[0].start == date(2024, 12, 15)
    assert windows[0].end == date(2024, 12, 31)
    assert windows[1].start == date(2025, 1, 1)
    assert windows[1].end == date(2025, 1, 5)
