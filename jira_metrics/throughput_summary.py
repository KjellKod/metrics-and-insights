"""Summaries over existing `jira_metrics/individual.py --csv` artifacts."""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from engineering_throughput.models import DateWindowConfig, JiraSummary, JiraTeamArtifact, JiraTeamSummary


POINTS_HEADER = "Assignee Released Points"
TICKETS_HEADER = "Assignee Released Tickets"


def _parse_month_label(value: str) -> str:
    return datetime.strptime(value, "%Y %b").strftime("%Y-%m")


def _parse_metric_section(rows: list[list[str]], start_index: int) -> tuple[tuple[str, ...], dict[str, dict[str, int]]]:
    header = rows[start_index]
    months = tuple(_parse_month_label(value) for value in header[1:] if value)
    values: dict[str, dict[str, int]] = {}
    for row in rows[start_index + 1 :]:
        if not row or not row[0]:
            break
        assignee = row[0]
        values[assignee] = {}
        for index, month in enumerate(months, start=1):
            raw_value = row[index] if index < len(row) else "0"
            values[assignee][month] = int(raw_value or 0)
    return months, values


def parse_individual_csv(path: Path, team_name: str | None = None) -> JiraTeamArtifact:
    """Parse one existing Jira individual metrics CSV artifact."""

    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))

    points_index = next((index for index, row in enumerate(rows) if row and row[0] == POINTS_HEADER), None)
    tickets_index = next((index for index, row in enumerate(rows) if row and row[0] == TICKETS_HEADER), None)
    if points_index is None or tickets_index is None:
        raise ValueError(f"{path} is missing expected Jira section headers")

    months, points = _parse_metric_section(rows, points_index)
    ticket_months, tickets = _parse_metric_section(rows, tickets_index)
    if months != ticket_months:
        raise ValueError(f"{path} points and tickets months do not match")

    name = team_name or path.stem.removesuffix("_individual_metrics")
    return JiraTeamArtifact(
        name=name,
        source_path=path,
        months=months,
        points_by_assignee=points,
        tickets_by_assignee=tickets,
    )


def _monthly_totals(metric_by_assignee: dict[str, dict[str, int]], months: tuple[str, ...]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for month in months:
        totals[month] = sum(values.get(month, 0) for values in metric_by_assignee.values())
    return totals


def _average(monthly_values: dict[str, int], months: tuple[str, ...]) -> float:
    if not months:
        return 0.0
    return round(sum(monthly_values.get(month, 0) for month in months) / len(months), 2)


def _points_per_ticket(points: dict[str, int], tickets: dict[str, int], months: tuple[str, ...]) -> float:
    total_points = sum(points.get(month, 0) for month in months)
    total_tickets = sum(tickets.get(month, 0) for month in months)
    if total_tickets == 0:
        return 0.0
    return round(total_points / total_tickets, 2)


def summarize_jira_artifacts(artifacts: list[JiraTeamArtifact], date_window: DateWindowConfig) -> JiraSummary:
    """Summarize parsed Jira team artifacts for the baseline/focus window."""

    all_team_points: defaultdict[str, int] = defaultdict(int)
    all_team_tickets: defaultdict[str, int] = defaultdict(int)
    team_summaries: list[JiraTeamSummary] = []
    for artifact in artifacts:
        monthly_points = _monthly_totals(artifact.points_by_assignee, artifact.months)
        monthly_tickets = _monthly_totals(artifact.tickets_by_assignee, artifact.months)
        for month, value in monthly_points.items():
            all_team_points[month] += value
        for month, value in monthly_tickets.items():
            all_team_tickets[month] += value

        team_summaries.append(
            JiraTeamSummary(
                name=artifact.name,
                monthly_points=monthly_points,
                monthly_tickets=monthly_tickets,
                points_by_assignee=artifact.points_by_assignee,
                tickets_by_assignee=artifact.tickets_by_assignee,
                baseline_avg_points=_average(monthly_points, date_window.baseline_months),
                focus_avg_points=_average(monthly_points, date_window.focus_months),
                baseline_avg_tickets=_average(monthly_tickets, date_window.baseline_months),
                focus_avg_tickets=_average(monthly_tickets, date_window.focus_months),
                baseline_points_per_ticket=_points_per_ticket(monthly_points, monthly_tickets, date_window.baseline_months),
                focus_points_per_ticket=_points_per_ticket(monthly_points, monthly_tickets, date_window.focus_months),
                first_focus_month=date_window.focus_months[0] if date_window.focus_months else None,
            )
        )

    team_summaries.sort(key=lambda item: item.name.lower())
    all_points = dict(sorted(all_team_points.items()))
    all_tickets = dict(sorted(all_team_tickets.items()))
    return JiraSummary(
        all_team_monthly_points=all_points,
        all_team_monthly_tickets=all_tickets,
        baseline_avg_points=_average(all_points, date_window.baseline_months),
        focus_avg_points=_average(all_points, date_window.focus_months),
        baseline_avg_tickets=_average(all_tickets, date_window.baseline_months),
        focus_avg_tickets=_average(all_tickets, date_window.focus_months),
        baseline_points_per_ticket=_points_per_ticket(all_points, all_tickets, date_window.baseline_months),
        focus_points_per_ticket=_points_per_ticket(all_points, all_tickets, date_window.focus_months),
        teams=tuple(team_summaries),
        source_artifacts=tuple(artifact.to_dict() for artifact in artifacts),
    )
