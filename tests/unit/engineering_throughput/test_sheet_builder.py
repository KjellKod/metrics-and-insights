from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from engineering_throughput.github_payload import build_github_sections
from engineering_throughput.jira_payload import build_jira_sections
from engineering_throughput.models import (
    DateWindowConfig,
    GitHubSummary,
    JiraSummary,
    JiraTeamSummary,
    PeriodMetrics,
    SheetSection,
    TeamConfig,
)
from engineering_throughput.sheet_builder import assemble_sheet_payload


def _date_window() -> DateWindowConfig:
    return DateWindowConfig(
        baseline_year=2025,
        focus_year=2026,
        start=date(2025, 1, 1),
        end=date(2026, 3, 31),
        focus_start=date(2026, 2, 1),
        baseline_months=("2025-01", "2025-02"),
        focus_months=("2026-02", "2026-03"),
        all_months=("2025-01", "2025-02", "2026-02", "2026-03"),
        baseline_label="2025 baseline",
        focus_label="2026 Feb-Mar",
        comparison_label="2025 baseline vs 2026 Feb-Mar",
    )


def _period(
    pr_count: int,
    avg: float,
    merge: float,
    approval: float | None,
    lines: float,
    large_rate: float,
    slow_rate: float,
    no_approval_rate: float,
) -> PeriodMetrics:
    return PeriodMetrics(
        pr_avg_per_month=avg,
        median_merge_hours=merge,
        median_first_review_hours=1.0,
        median_first_approval_hours=approval,
        median_lines_changed=lines,
        large_pr_count=1,
        slow_merge_count=1,
        no_approval_count=1,
        large_pr_rate=large_rate,
        slow_merge_rate=slow_rate,
        no_approval_rate=no_approval_rate,
        pr_count=pr_count,
    )


def _github_summary() -> GitHubSummary:
    return GitHubSummary(
        raw_baseline=_period(10, 5.0, 20.0, 6.0, 100.0, 10.0, 20.0, 5.0),
        raw_focus=_period(16, 8.0, 18.0, 8.0, 150.0, 12.0, 18.0, 6.0),
        eligible_baseline=_period(9, 4.5, 19.0, 5.0, 95.0, 9.0, 18.0, 4.0),
        eligible_focus=_period(14, 7.0, 17.0, 7.0, 140.0, 14.0, 16.0, 5.0),
        monthly_trend=(
            {
                "month": "2025-01",
                "raw_pr_count": 4,
                "eligible_pr_count": 4,
                "excluded_pr_count": 0,
                "median_merge_hours": 20.0,
                "median_first_approval_hours": 5.0,
                "median_lines_changed": 90.0,
                "large_pr_rate": 10.0,
                "slow_merge_rate": 20.0,
                "no_approval_rate": 4.0,
            },
            {
                "month": "2026-02",
                "raw_pr_count": 8,
                "eligible_pr_count": 7,
                "excluded_pr_count": 1,
                "median_merge_hours": 18.0,
                "median_first_approval_hours": 7.0,
                "median_lines_changed": 140.0,
                "large_pr_rate": 14.0,
                "slow_merge_rate": 16.0,
                "no_approval_rate": 5.0,
            },
        ),
        repo_comparison=(
            {
                "repo": "api",
                "baseline_raw_pr_avg": 3.0,
                "focus_raw_pr_avg": 5.0,
                "raw_pr_avg_delta": 2.0,
                "baseline_merge_hours": 20.0,
                "focus_merge_hours": 18.0,
                "baseline_large_pr_rate": 10.0,
                "focus_large_pr_rate": 14.0,
                "baseline_slow_merge_rate": 20.0,
                "focus_slow_merge_rate": 16.0,
                "focus_no_approval_count": 1,
            },
        ),
        author_comparison=(
            {
                "author": "alex",
                "baseline_raw_pr_avg": 2.0,
                "focus_raw_pr_avg": 4.0,
                "raw_pr_avg_delta": 2.0,
                "baseline_merge_hours": 20.0,
                "focus_merge_hours": 18.0,
                "baseline_large_pr_rate": 10.0,
                "focus_large_pr_rate": 14.0,
                "baseline_no_approval_rate": 4.0,
                "focus_no_approval_rate": 5.0,
            },
        ),
        author_monthly=(
            {"month": "2025-01", "counts": {"alex": 2}},
            {"month": "2026-02", "counts": {"alex": 4}},
        ),
        flagged_authors=(
            {"author": "alex", "flagged_prs": 2, "large_prs": 1, "slow_merges": 1, "no_approval_prs": 0},
        ),
        flagged_pr_sample=(
            {
                "month": "2026-02",
                "repo": "api",
                "pr_number": 7,
                "author": "alex",
                "hours_to_merge": 18.0,
                "lines_changed": 900,
                "large_pr": False,
                "slow_merge": False,
                "no_approval": False,
                "title": "feature",
                "url": "https://example.com/api/7",
            },
        ),
        no_approval_audit=(
            {"month": "2026-02", "repo": "api", "pr_number": 7, "author": "alex", "title": "feature", "status": "counted", "reason": ""},
        ),
        exclusion_reason_counts={"hackathon": 1},
        eligible_rows=(),
        excluded_rows=(),
    )


def _jira_summary() -> JiraSummary:
    team = JiraTeamSummary(
        name="Platform",
        monthly_points={"2025-01": 8, "2025-02": 10, "2026-02": 12, "2026-03": 14},
        monthly_tickets={"2025-01": 2, "2025-02": 3, "2026-02": 4, "2026-03": 5},
        points_by_assignee={"Alex": {"2025-01": 5, "2026-02": 6}},
        tickets_by_assignee={"Alex": {"2025-01": 1, "2026-02": 2}},
        baseline_avg_points=9.0,
        focus_avg_points=13.0,
        baseline_avg_tickets=2.5,
        focus_avg_tickets=4.5,
        baseline_points_per_ticket=3.6,
        focus_points_per_ticket=2.89,
        first_focus_month="2026-02",
    )
    return JiraSummary(
        all_team_monthly_points={"2025-01": 8, "2025-02": 10, "2026-02": 12, "2026-03": 14},
        all_team_monthly_tickets={"2025-01": 2, "2025-02": 3, "2026-02": 4, "2026-03": 5},
        baseline_avg_points=9.0,
        focus_avg_points=13.0,
        baseline_avg_tickets=2.5,
        focus_avg_tickets=4.5,
        baseline_points_per_ticket=3.6,
        focus_points_per_ticket=2.89,
        teams=(team,),
        source_artifacts=(),
    )


def test_sheet_builder_computes_ranges_from_table_sizes() -> None:
    sections = build_github_sections(_github_summary(), _date_window())
    payload = assemble_sheet_payload(sections)

    assert payload.data[0]["range"].startswith("'GitHub Summary'!A1:")
    assert payload.data[0]["range"] != "'GitHub Summary'!A1:O80"
    assert len(payload.tabs) == 5


def test_jira_sections_backfill_zero_months_from_date_window() -> None:
    sections = build_jira_sections(
        _jira_summary(),
        (TeamConfig(name="Platform", jira_csv=Path("platform.csv"), repos=("api",)),),
        DateWindowConfig(
            baseline_year=2025,
            focus_year=2026,
            start=date(2025, 1, 1),
            end=date(2026, 3, 31),
            focus_start=date(2026, 2, 1),
            baseline_months=("2025-01", "2025-02"),
            focus_months=("2026-02", "2026-03"),
            all_months=("2025-01", "2025-02", "2025-03", "2026-01", "2026-02", "2026-03"),
            baseline_label="2025 baseline",
            focus_label="2026 Feb-Mar",
            comparison_label="2025 baseline vs 2026 Feb-Mar",
        ),
    )

    jira_summary_section = next(section for section in sections if section.title == "Jira Summary")
    team_section = next(section for section in sections if section.title == "Platform")

    assert ["2025-03", 0, 0] in jira_summary_section.values
    assert ["2026-01", 0, 0] in jira_summary_section.values
    assert ["2025-03", 0, 0] in team_section.values
    assert ["Alex", 5, 0, 0, 0, 6, 0] in team_section.values
def test_github_payload_caps_audit_and_sample_rows_for_sheet_use() -> None:
    github_summary = _github_summary()
    github_summary = replace(
        github_summary,
        author_comparison=tuple(
            {
                "author": f"author-{index}",
                "baseline_raw_pr_avg": 1.0,
                "focus_raw_pr_avg": 2.0,
                "raw_pr_avg_delta": 1.0,
                "baseline_merge_hours": 10.0,
                "focus_merge_hours": 8.0,
                "baseline_large_pr_rate": 5.0,
                "focus_large_pr_rate": 7.0,
                "baseline_no_approval_rate": 1.0,
                "focus_no_approval_rate": 2.0,
            }
            for index in range(30)
        ),
        no_approval_audit=tuple(
            {
                "month": "2026-02",
                "repo": "api",
                "pr_number": index,
                "author": f"author-{index}",
                "title": f"feature-{index}",
                "status": "counted",
                "reason": "",
            }
            for index in range(45)
        ),
        flagged_pr_sample=tuple(
            {
                "month": "2026-02",
                "repo": "api",
                "pr_number": index,
                "author": f"author-{index}",
                "hours_to_merge": 18.0,
                "lines_changed": 900,
                "large_pr": False,
                "slow_merge": False,
                "no_approval": False,
                "title": f"feature-{index}",
                "url": f"https://example.com/api/{index}",
            }
            for index in range(35)
        ),
    )

    sections = build_github_sections(github_summary, _date_window())
    authors = next(section for section in sections if section.title == "GitHub Authors")
    no_approval = next(section for section in sections if section.title == "GitHub No Approval")
    flags = next(section for section in sections if section.title == "GitHub Flags")

    assert len([row for row in authors.values if row and str(row[0]).startswith("author-")]) == 25
    assert any("additional rows kept locally" in str(row[-1]) for row in no_approval.values if row)
    assert any(any("additional rows kept locally" in str(cell) for cell in row) for row in flags.values if row)


def test_sheet_builder_escapes_apostrophes_in_tab_titles() -> None:
    payload = assemble_sheet_payload([SheetSection(title="Manager's Team", values=[[1]])])

    assert payload.data[0]["range"] == "'Manager''s Team'!A1:A1"


def test_sheet_builder_rejects_duplicate_titles() -> None:
    with pytest.raises(ValueError, match="Duplicate sheet title"):
        assemble_sheet_payload(
            [
                SheetSection(title="Jira Summary", values=[[1]]),
                SheetSection(title="Jira Summary", values=[[2]]),
            ]
        )
