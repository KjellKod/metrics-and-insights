"""Payload builders for Jira throughput summary and team tabs."""

from __future__ import annotations

from typing import Any

from engineering_throughput.models import DateWindowConfig, JiraSummary, SheetSection, TeamConfig


def _monthly_rows(label: str, months: tuple[str, ...], monthly_points: dict[str, int], monthly_tickets: dict[str, int]) -> list[list[Any]]:
    rows = [[label], ["Month", "Completed points", "Completed tickets"]]
    for month in months:
        rows.append([month, monthly_points.get(month, 0), monthly_tickets.get(month, 0)])
    return rows


def _assignee_rows(header: str, months: tuple[str, ...], values_by_assignee: dict[str, dict[str, int]]) -> list[list[Any]]:
    rows = [[header], ["Assignee", *months]]
    for assignee in sorted(values_by_assignee):
        rows.append([assignee] + [values_by_assignee[assignee].get(month, 0) for month in months])
    return rows


def build_jira_sections(summary: JiraSummary, team_config: tuple[TeamConfig, ...], date_window: DateWindowConfig) -> list[SheetSection]:
    """Build Jira Summary plus optional runtime team tabs."""

    summary_values = [
        ["Jira Summary"],
        ["Comparison", date_window.comparison_label],
        [],
        ["Metric", date_window.baseline_label, date_window.focus_label],
        ["Completed points per month", summary.baseline_avg_points, summary.focus_avg_points],
        ["Completed tickets per month", summary.baseline_avg_tickets, summary.focus_avg_tickets],
        ["Points per completed ticket", summary.baseline_points_per_ticket, summary.focus_points_per_ticket],
        [],
    ] + _monthly_rows(
        "All-team monthly totals",
        date_window.all_months,
        summary.all_team_monthly_points,
        summary.all_team_monthly_tickets,
    )

    if team_config:
        summary_values.extend([[""], ["Team comparison"], ["Team", "Baseline points/mo", "Focus points/mo", "Baseline tickets/mo", "Focus tickets/mo", "Baseline points/ticket", "Focus points/ticket"]])
        for team in summary.teams:
            summary_values.append(
                [
                    team.name,
                    team.baseline_avg_points,
                    team.focus_avg_points,
                    team.baseline_avg_tickets,
                    team.focus_avg_tickets,
                    team.baseline_points_per_ticket,
                    team.focus_points_per_ticket,
                ]
            )

    sections = [SheetSection(title="Jira Summary", values=summary_values)]
    if not team_config:
        return sections

    summary_by_name = {team.name: team for team in summary.teams}
    for team in team_config:
        team_summary = summary_by_name.get(team.name)
        if team_summary is None:
            continue
        values = [
            [team.name],
            ["Source", str(team.jira_csv)],
            ["Comparison", date_window.comparison_label],
            ["First focus month", team_summary.first_focus_month or ""],
            [],
            ["Metric", date_window.baseline_label, date_window.focus_label],
            ["Completed points per month", team_summary.baseline_avg_points, team_summary.focus_avg_points],
            ["Completed tickets per month", team_summary.baseline_avg_tickets, team_summary.focus_avg_tickets],
            ["Points per completed ticket", team_summary.baseline_points_per_ticket, team_summary.focus_points_per_ticket],
            [],
        ]
        values.extend(
            _monthly_rows(
                "Team monthly totals",
                date_window.all_months,
                team_summary.monthly_points,
                team_summary.monthly_tickets,
            )
        )
        values.extend([[""]])
        values.extend(_assignee_rows("Individual released points", date_window.all_months, team_summary.points_by_assignee))
        values.extend([[""]])
        values.extend(_assignee_rows("Individual released tickets", date_window.all_months, team_summary.tickets_by_assignee))
        sections.append(SheetSection(title=team.name, values=values))

    return sections
