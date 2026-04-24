"""Structured recommendation inputs and agent-authored section loading."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from engineering_throughput.models import (
    DateWindowConfig,
    GitHubSummary,
    JiraSummary,
    RecommendationSignals,
    SheetSection,
    TeamConfig,
)


def _direction(focus_value: float | None, baseline_value: float | None) -> str:
    if focus_value is None or baseline_value is None:
        return "unknown"
    if focus_value > baseline_value:
        return "up"
    if focus_value < baseline_value:
        return "down"
    return "flat"


def build_recommendation_signals(
    jira_summary: JiraSummary,
    github_summary: GitHubSummary,
    team_config: tuple[TeamConfig, ...],
    date_window: DateWindowConfig,
) -> RecommendationSignals:
    """Build structured signals for an external agent recommendation pass."""

    teams_by_name = {team.name: team for team in jira_summary.teams}
    team_signals: list[dict[str, Any]] = []
    for team in team_config:
        summary = teams_by_name.get(team.name)
        if summary is None:
            continue
        team_signals.append(
            {
                "team": team.name,
                "baseline_avg_points": summary.baseline_avg_points,
                "focus_avg_points": summary.focus_avg_points,
                "points_direction": _direction(summary.focus_avg_points, summary.baseline_avg_points),
                "baseline_avg_tickets": summary.baseline_avg_tickets,
                "focus_avg_tickets": summary.focus_avg_tickets,
                "tickets_direction": _direction(summary.focus_avg_tickets, summary.baseline_avg_tickets),
                "baseline_points_per_ticket": summary.baseline_points_per_ticket,
                "focus_points_per_ticket": summary.focus_points_per_ticket,
                "points_per_ticket_direction": _direction(
                    summary.focus_points_per_ticket,
                    summary.baseline_points_per_ticket,
                ),
                "repos": list(team.repos),
            }
        )

    return RecommendationSignals(
        comparison_label=date_window.comparison_label,
        github={
            "raw_throughput": {
                "baseline_avg_prs_per_month": github_summary.raw_baseline.pr_avg_per_month,
                "focus_avg_prs_per_month": github_summary.raw_focus.pr_avg_per_month,
                "direction": _direction(
                    github_summary.raw_focus.pr_avg_per_month,
                    github_summary.raw_baseline.pr_avg_per_month,
                ),
            },
            "process_eligible_throughput": {
                "baseline_avg_prs_per_month": github_summary.eligible_baseline.pr_avg_per_month,
                "focus_avg_prs_per_month": github_summary.eligible_focus.pr_avg_per_month,
                "direction": _direction(
                    github_summary.eligible_focus.pr_avg_per_month,
                    github_summary.eligible_baseline.pr_avg_per_month,
                ),
            },
            "merge_time_hours": {
                "baseline_median": github_summary.eligible_baseline.median_merge_hours,
                "focus_median": github_summary.eligible_focus.median_merge_hours,
                "direction": _direction(
                    github_summary.eligible_focus.median_merge_hours,
                    github_summary.eligible_baseline.median_merge_hours,
                ),
            },
            "first_approval_hours": {
                "baseline_median": github_summary.eligible_baseline.median_first_approval_hours,
                "focus_median": github_summary.eligible_focus.median_first_approval_hours,
                "direction": _direction(
                    github_summary.eligible_focus.median_first_approval_hours,
                    github_summary.eligible_baseline.median_first_approval_hours,
                ),
            },
            "large_pr_rate": {
                "baseline_rate": github_summary.eligible_baseline.large_pr_rate,
                "focus_rate": github_summary.eligible_focus.large_pr_rate,
                "direction": _direction(
                    github_summary.eligible_focus.large_pr_rate,
                    github_summary.eligible_baseline.large_pr_rate,
                ),
            },
            "no_approval_rate": {
                "baseline_rate": github_summary.eligible_baseline.no_approval_rate,
                "focus_rate": github_summary.eligible_focus.no_approval_rate,
                "direction": _direction(
                    github_summary.eligible_focus.no_approval_rate,
                    github_summary.eligible_baseline.no_approval_rate,
                ),
            },
            "exclusion_reason_counts": dict(github_summary.exclusion_reason_counts),
        },
        jira={
            "baseline_avg_points": jira_summary.baseline_avg_points,
            "focus_avg_points": jira_summary.focus_avg_points,
            "points_direction": _direction(jira_summary.focus_avg_points, jira_summary.baseline_avg_points),
            "baseline_avg_tickets": jira_summary.baseline_avg_tickets,
            "focus_avg_tickets": jira_summary.focus_avg_tickets,
            "tickets_direction": _direction(
                jira_summary.focus_avg_tickets,
                jira_summary.baseline_avg_tickets,
            ),
            "baseline_points_per_ticket": jira_summary.baseline_points_per_ticket,
            "focus_points_per_ticket": jira_summary.focus_points_per_ticket,
            "points_per_ticket_direction": _direction(
                jira_summary.focus_points_per_ticket,
                jira_summary.baseline_points_per_ticket,
            ),
        },
        teams=tuple(team_signals),
    )


def load_agent_recommendations_section(path: Path) -> SheetSection:
    """Load an agent-authored Recommendations section JSON file."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Recommendations file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in recommendations file {path}: {exc.msg}") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"Recommendations file must be a JSON object: {path}")

    title = payload.get("title")
    values = payload.get("values")
    notes = payload.get("notes", {})

    if title != "Recommendations":
        raise ValueError("Recommendations file must set title='Recommendations'")
    if not isinstance(values, list) or not values or not all(isinstance(row, list) for row in values):
        raise ValueError("Recommendations file must contain a non-empty list-of-lists 'values' field")
    if not isinstance(notes, dict):
        raise ValueError("Recommendations file field 'notes' must be an object when provided")

    return SheetSection(title=title, values=values, notes=notes)
