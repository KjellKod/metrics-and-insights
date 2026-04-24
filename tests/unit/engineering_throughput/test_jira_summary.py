from __future__ import annotations

from datetime import date
from pathlib import Path

from engineering_throughput.models import DateWindowConfig
from jira_metrics.throughput_summary import parse_individual_csv, summarize_jira_artifacts


FIXTURE_DIR = Path("tests/fixtures/engineering_throughput")


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


def test_parse_individual_csv_extracts_points_and_ticket_sections() -> None:
    artifact = parse_individual_csv(FIXTURE_DIR / "alpha_individual_metrics.csv", team_name="Alpha Team")

    assert artifact.name == "Alpha Team"
    assert artifact.months == ("2025-01", "2025-02", "2026-02", "2026-03")
    assert artifact.points_by_assignee["Alex"]["2026-02"] == 8
    assert artifact.tickets_by_assignee["Blair"]["2026-03"] == 2


def test_summarize_jira_artifacts_computes_team_and_all_team_comparisons() -> None:
    artifacts = [
        parse_individual_csv(FIXTURE_DIR / "alpha_individual_metrics.csv", team_name="Alpha Team"),
        parse_individual_csv(FIXTURE_DIR / "beta_individual_metrics.csv", team_name="Beta Team"),
    ]

    summary = summarize_jira_artifacts(artifacts, _date_window())

    assert summary.baseline_avg_points == 10.5
    assert summary.focus_avg_points == 16.5
    assert summary.baseline_avg_tickets == 3.5
    assert summary.focus_avg_tickets == 5.0
    assert {team.name for team in summary.teams} == {"Alpha Team", "Beta Team"}
