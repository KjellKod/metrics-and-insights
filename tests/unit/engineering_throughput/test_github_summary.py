from __future__ import annotations

from dataclasses import replace
import json
from datetime import date
from pathlib import Path

from engineering_throughput.date_ranges import resolve_date_window
from engineering_throughput.models import ExcludeConfig, JiraSource, RunConfig
from git_metrics.throughput_summary import build_process_eligibility, summarize_github_rows


FIXTURE_DIR = Path("tests/fixtures/engineering_throughput")


def _config() -> RunConfig:
    exclude_config = json.loads((FIXTURE_DIR / "exclude-config.json").read_text(encoding="utf-8"))
    return RunConfig(
        owner="example-org",
        requested_repos=("api", "mobile"),
        repos=("api", "mobile"),
        repo_source="cli",
        env_file=Path(".env"),
        output_dir=Path(".ws/test"),
        date_window=resolve_date_window(
            baseline_year=2025,
            focus_year=2026,
            focus_start=date(2026, 2, 1),
            date_end=date(2026, 4, 30),
            today=date(2026, 4, 30),
        ),
        jira_source=JiraSource(mode="directory", directory=FIXTURE_DIR, artifacts=()),
        teams=(),
        team_config_path=None,
        exclude_config_path=FIXTURE_DIR / "exclude-config.json",
        exclude_config=ExcludeConfig(
            windows=tuple(),
            rules=tuple(),
        ),
        recommendations_file=None,
        spreadsheet_mode="create",
        spreadsheet_id=None,
    )


def _config_with_exclusions() -> RunConfig:
    from engineering_throughput.config import load_exclude_config

    config = _config()
    return replace(config, exclude_config=load_exclude_config(FIXTURE_DIR / "exclude-config.json"))


def _rows() -> list[dict]:
    return [
        {
            "month": "2025-01",
            "repo": "api",
            "pr_number": 1,
            "title": "feature api",
            "url": "https://example.com/api/1",
            "author": "alice",
            "created_at": "2025-01-01T00:00:00+00:00",
            "merged_at": "2025-01-01T12:00:00+00:00",
            "hours_to_merge": 12.0,
            "hours_to_first_review": 2.0,
            "hours_to_first_approval": 4.0,
            "additions": 50,
            "deletions": 10,
            "changed_files": 2,
            "lines_changed": 60,
            "review_count": 2,
            "approval_count": 1,
            "reviewer_count": 1,
            "large_pr": False,
            "slow_merge": False,
            "no_approval": False,
        },
        {
            "month": "2026-02",
            "repo": "api",
            "pr_number": 2,
            "title": "feature web no approval",
            "url": "https://example.com/api/2",
            "author": "alice",
            "created_at": "2026-02-01T00:00:00+00:00",
            "merged_at": "2026-02-02T12:00:00+00:00",
            "hours_to_merge": 36.0,
            "hours_to_first_review": 3.0,
            "hours_to_first_approval": None,
            "additions": 100,
            "deletions": 20,
            "changed_files": 4,
            "lines_changed": 120,
            "review_count": 1,
            "approval_count": 0,
            "reviewer_count": 1,
            "large_pr": False,
            "slow_merge": False,
            "no_approval": True,
        },
        {
            "month": "2026-02",
            "repo": "mobile",
            "pr_number": 3,
            "title": "release promotion for mobile",
            "url": "https://example.com/mobile/3",
            "author": "release-bot",
            "created_at": "2026-02-12T00:00:00+00:00",
            "merged_at": "2026-02-12T10:00:00+00:00",
            "hours_to_merge": 10.0,
            "hours_to_first_review": 1.0,
            "hours_to_first_approval": None,
            "additions": 10,
            "deletions": 2,
            "changed_files": 1,
            "lines_changed": 12,
            "review_count": 0,
            "approval_count": 0,
            "reviewer_count": 0,
            "large_pr": False,
            "slow_merge": False,
            "no_approval": True,
        },
        {
            "month": "2026-03",
            "repo": "api",
            "pr_number": 4,
            "title": "large migration",
            "url": "https://example.com/api/4",
            "author": "bob",
            "created_at": "2026-03-01T00:00:00+00:00",
            "merged_at": "2026-03-05T06:00:00+00:00",
            "hours_to_merge": 102.0,
            "hours_to_first_review": 20.0,
            "hours_to_first_approval": 24.0,
            "additions": 900,
            "deletions": 300,
            "changed_files": 20,
            "lines_changed": 1200,
            "review_count": 2,
            "approval_count": 1,
            "reviewer_count": 2,
            "large_pr": True,
            "slow_merge": True,
            "no_approval": False,
        },
    ]


def test_process_eligible_metrics_exclude_configured_special_cases() -> None:
    config = _config_with_exclusions()
    eligibility = build_process_eligibility(_rows(), config.exclude_config)

    assert len(eligibility.eligible_rows) == 3
    assert len(eligibility.excluded_rows) == 1
    assert eligibility.reason_counts == {"hackathon": 1, "release-promotion": 1}


def test_repo_author_and_flag_outputs_are_data_driven() -> None:
    summary = summarize_github_rows(_rows(), _config_with_exclusions())

    repo_names = {row["repo"] for row in summary.repo_comparison}
    author_names = {row["author"] for row in summary.author_comparison}
    flagged_authors = {row["author"] for row in summary.flagged_authors}

    assert repo_names == {"api", "mobile"}
    assert author_names == {"alice", "bob", "release-bot"}
    assert flagged_authors == {"alice", "bob"}


def test_no_approval_audit_keeps_raw_and_excluded_counts_visible() -> None:
    summary = summarize_github_rows(_rows(), _config_with_exclusions())

    assert summary.raw_focus.pr_count == 3
    assert summary.eligible_focus.pr_count == 2
    assert any(row["status"] == "counted" for row in summary.no_approval_audit)
    assert any(row["status"] == "excluded" for row in summary.no_approval_audit)
