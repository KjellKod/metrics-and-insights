from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from engineering_throughput.models import (
    DateWindowConfig,
    GitHubSummary,
    JiraSummary,
    JiraTeamSummary,
    PeriodMetrics,
    TeamConfig,
)
from engineering_throughput.recommendation_signals import (
    build_recommendation_signals,
    load_agent_recommendations_section,
)


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


def _period(pr_avg: float, approval: float | None, large_rate: float, no_approval_rate: float) -> PeriodMetrics:
    return PeriodMetrics(
        pr_avg_per_month=pr_avg,
        median_merge_hours=12.0,
        median_first_review_hours=3.0,
        median_first_approval_hours=approval,
        median_lines_changed=120.0,
        large_pr_count=1,
        slow_merge_count=0,
        no_approval_count=1,
        large_pr_rate=large_rate,
        slow_merge_rate=0.0,
        no_approval_rate=no_approval_rate,
        pr_count=10,
    )


def _github_summary() -> GitHubSummary:
    return GitHubSummary(
        raw_baseline=_period(5.0, 5.0, 9.0, 4.0),
        raw_focus=_period(8.0, 7.0, 14.0, 5.0),
        eligible_baseline=_period(4.5, 5.0, 9.0, 4.0),
        eligible_focus=_period(7.0, 7.0, 14.0, 5.0),
        monthly_trend=(),
        repo_comparison=(),
        author_comparison=(),
        author_monthly=(),
        flagged_authors=(),
        flagged_pr_sample=(),
        no_approval_audit=(),
        exclusion_reason_counts={"hackathon": 1},
        eligible_rows=(),
        excluded_rows=(),
    )


def _jira_summary() -> JiraSummary:
    team = JiraTeamSummary(
        name="Platform",
        monthly_points={},
        monthly_tickets={},
        points_by_assignee={},
        tickets_by_assignee={},
        baseline_avg_points=9.0,
        focus_avg_points=13.0,
        baseline_avg_tickets=2.5,
        focus_avg_tickets=4.5,
        baseline_points_per_ticket=3.6,
        focus_points_per_ticket=2.9,
        first_focus_month="2026-02",
    )
    return JiraSummary(
        all_team_monthly_points={},
        all_team_monthly_tickets={},
        baseline_avg_points=9.0,
        focus_avg_points=13.0,
        baseline_avg_tickets=2.5,
        focus_avg_tickets=4.5,
        baseline_points_per_ticket=3.6,
        focus_points_per_ticket=2.9,
        teams=(team,),
        source_artifacts=(),
    )


def test_build_recommendation_signals_emits_structured_facts_only() -> None:
    signals = build_recommendation_signals(
        _jira_summary(),
        _github_summary(),
        (TeamConfig(name="Platform", jira_csv=Path("platform.csv"), repos=("api",)),),
        _date_window(),
    )

    payload = signals.to_dict()
    assert payload["comparison_label"] == "2025 baseline vs 2026 Feb-Mar"
    assert payload["github"]["raw_throughput"]["direction"] == "up"
    assert payload["github"]["large_pr_rate"]["direction"] == "up"
    assert payload["jira"]["points_direction"] == "up"
    assert payload["teams"][0]["team"] == "Platform"
    assert "Suggested action" not in json.dumps(payload)


def test_load_agent_recommendations_section_validates_shape(tmp_path: Path) -> None:
    path = tmp_path / "recommendations.json"
    path.write_text(
        json.dumps(
            {
                "title": "Recommendations",
                "values": [["Recommendations"], ["Audience", "Observation"]],
                "notes": {"author": "agent"},
            }
        ),
        encoding="utf-8",
    )

    section = load_agent_recommendations_section(path)

    assert section.title == "Recommendations"
    assert section.values[0] == ["Recommendations"]


def test_load_agent_recommendations_section_rejects_invalid_shape(tmp_path: Path) -> None:
    path = tmp_path / "recommendations.json"
    path.write_text(json.dumps({"title": "Wrong", "values": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="title='Recommendations'"):
        load_agent_recommendations_section(path)
