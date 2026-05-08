from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest
import requests

from git_metrics.ci_maturity_report import GitHubClient
from git_metrics.org_merged_prs_per_month import (
    build_argument_parser,
    collect_report,
    count_merged_prs_for_window,
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
        self.headers: dict[str, str] = {}

    def get(self, url: str, *, params: dict[str, Any] | None = None, timeout: float = 0) -> _StubResponse:
        self.calls.append((url, dict(params) if params is not None else None))
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


def test_month_windows_sanity_check_for_year_boundaries() -> None:
    # Guard against off-by-one when the range spans Dec/Jan.
    windows = month_windows(date(2024, 12, 15), date(2025, 1, 5))
    assert [w.label for w in windows] == ["2024-12", "2025-01"]
    assert windows[0].start == date(2024, 12, 15)
    assert windows[0].end == date(2024, 12, 31)
    assert windows[1].start == date(2025, 1, 1)
    assert windows[1].end == date(2025, 1, 5)
