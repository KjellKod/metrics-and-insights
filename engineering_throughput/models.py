"""Shared models for engineering throughput collection and payload generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any


def _path_string(path: Path | None) -> str | None:
    return None if path is None else str(path)


@dataclass(frozen=True)
class DateWindowConfig:
    """Canonical runtime date window and generated labels."""

    baseline_year: int
    focus_year: int
    start: date
    end: date
    focus_start: date
    baseline_months: tuple[str, ...]
    focus_months: tuple[str, ...]
    all_months: tuple[str, ...]
    baseline_label: str
    focus_label: str
    comparison_label: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_year": self.baseline_year,
            "focus_year": self.focus_year,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "focus_start": self.focus_start.isoformat(),
            "baseline_months": list(self.baseline_months),
            "focus_months": list(self.focus_months),
            "all_months": list(self.all_months),
            "baseline_label": self.baseline_label,
            "focus_label": self.focus_label,
            "comparison_label": self.comparison_label,
        }


@dataclass(frozen=True)
class TeamConfig:
    """Team runtime metadata loaded from the optional team config file."""

    name: str
    jira_csv: Path
    repos: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "jira_csv": str(self.jira_csv),
            "repos": list(self.repos),
        }


@dataclass(frozen=True)
class JiraSource:
    """Resolved Jira artifact source contract used by the build."""

    mode: str
    directory: Path | None = None
    artifacts: tuple[Path, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "directory": _path_string(self.directory),
            "artifacts": [str(path) for path in self.artifacts],
        }


@dataclass(frozen=True)
class ExcludeWindow:
    """A date window whose rows should be excluded from process metrics."""

    name: str
    start: date
    end: date

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
        }


@dataclass(frozen=True)
class ExcludeRule:
    """A row-matching rule for excluding PRs from process metrics."""

    reason: str
    repos: tuple[str, ...] = ()
    authors: tuple[str, ...] = ()
    title_contains: tuple[str, ...] = ()
    start: date | None = None
    end: date | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "repos": list(self.repos),
            "authors": list(self.authors),
            "title_contains": list(self.title_contains),
            "start": None if self.start is None else self.start.isoformat(),
            "end": None if self.end is None else self.end.isoformat(),
        }


@dataclass(frozen=True)
class ExcludeConfig:
    """All configured exclusion windows and row-matching rules."""

    windows: tuple[ExcludeWindow, ...] = ()
    rules: tuple[ExcludeRule, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "windows": [window.to_dict() for window in self.windows],
            "rules": [rule.to_dict() for rule in self.rules],
        }


@dataclass(frozen=True)
class RunConfig:
    """Resolved runtime configuration shared by the build scripts."""

    owner: str
    requested_repos: tuple[str, ...]
    repos: tuple[str, ...]
    repo_source: str
    env_file: Path
    output_dir: Path
    date_window: DateWindowConfig
    jira_source: JiraSource
    teams: tuple[TeamConfig, ...]
    team_config_path: Path | None
    exclude_config_path: Path | None
    exclude_config: ExcludeConfig
    spreadsheet_mode: str
    spreadsheet_id: str | None
    show_config: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner": self.owner,
            "requested_repos": list(self.requested_repos),
            "repos": list(self.repos),
            "repo_source": self.repo_source,
            "env_file": str(self.env_file),
            "output_dir": str(self.output_dir),
            "date_window": self.date_window.to_dict(),
            "jira_source": self.jira_source.to_dict(),
            "teams": [team.to_dict() for team in self.teams],
            "team_config_path": _path_string(self.team_config_path),
            "exclude_config_path": _path_string(self.exclude_config_path),
            "exclude_config": self.exclude_config.to_dict(),
            "spreadsheet_mode": self.spreadsheet_mode,
            "spreadsheet_id": self.spreadsheet_id,
            "show_config": self.show_config,
        }


@dataclass(frozen=True)
class RepoAccessIssue:
    """A repo that could not be queried for GitHub metrics."""

    repo: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"repo": self.repo, "reason": self.reason}


@dataclass(frozen=True)
class GitHubCollection:
    """Raw GitHub PR detail rows plus repo validation results."""

    owner: str
    requested_repos: tuple[str, ...]
    repos: tuple[str, ...]
    inaccessible_repos: tuple[RepoAccessIssue, ...]
    detail_rows: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner": self.owner,
            "requested_repos": list(self.requested_repos),
            "repos": list(self.repos),
            "inaccessible_repos": [issue.to_dict() for issue in self.inaccessible_repos],
            "detail_rows": list(self.detail_rows),
        }


@dataclass(frozen=True)
class PeriodMetrics:
    """Comparable PR period metrics for raw or process-eligible rows."""

    pr_avg_per_month: float
    median_merge_hours: float | None
    median_first_review_hours: float | None
    median_first_approval_hours: float | None
    median_lines_changed: float | None
    large_pr_count: int
    slow_merge_count: int
    no_approval_count: int
    large_pr_rate: float
    slow_merge_rate: float
    no_approval_rate: float
    pr_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "pr_avg_per_month": self.pr_avg_per_month,
            "median_merge_hours": self.median_merge_hours,
            "median_first_review_hours": self.median_first_review_hours,
            "median_first_approval_hours": self.median_first_approval_hours,
            "median_lines_changed": self.median_lines_changed,
            "large_pr_count": self.large_pr_count,
            "slow_merge_count": self.slow_merge_count,
            "no_approval_count": self.no_approval_count,
            "large_pr_rate": self.large_pr_rate,
            "slow_merge_rate": self.slow_merge_rate,
            "no_approval_rate": self.no_approval_rate,
            "pr_count": self.pr_count,
        }


@dataclass(frozen=True)
class ProcessEligibilityResult:
    """PR rows partitioned into eligible vs excluded process metrics."""

    eligible_rows: tuple[dict[str, Any], ...]
    excluded_rows: tuple[dict[str, Any], ...]
    reason_counts: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "eligible_rows": list(self.eligible_rows),
            "excluded_rows": list(self.excluded_rows),
            "reason_counts": dict(self.reason_counts),
        }


@dataclass(frozen=True)
class GitHubSummary:
    """GitHub-only summary objects used by sheet builders."""

    raw_baseline: PeriodMetrics
    raw_focus: PeriodMetrics
    eligible_baseline: PeriodMetrics
    eligible_focus: PeriodMetrics
    monthly_trend: tuple[dict[str, Any], ...]
    repo_comparison: tuple[dict[str, Any], ...]
    author_comparison: tuple[dict[str, Any], ...]
    author_monthly: tuple[dict[str, Any], ...]
    flagged_authors: tuple[dict[str, Any], ...]
    flagged_pr_sample: tuple[dict[str, Any], ...]
    no_approval_audit: tuple[dict[str, Any], ...]
    exclusion_reason_counts: dict[str, int]
    eligible_rows: tuple[dict[str, Any], ...] = ()
    excluded_rows: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_baseline": self.raw_baseline.to_dict(),
            "raw_focus": self.raw_focus.to_dict(),
            "eligible_baseline": self.eligible_baseline.to_dict(),
            "eligible_focus": self.eligible_focus.to_dict(),
            "monthly_trend": list(self.monthly_trend),
            "repo_comparison": list(self.repo_comparison),
            "author_comparison": list(self.author_comparison),
            "author_monthly": list(self.author_monthly),
            "flagged_authors": list(self.flagged_authors),
            "flagged_pr_sample": list(self.flagged_pr_sample),
            "no_approval_audit": list(self.no_approval_audit),
            "exclusion_reason_counts": dict(self.exclusion_reason_counts),
            "eligible_rows": list(self.eligible_rows),
            "excluded_rows": list(self.excluded_rows),
        }


@dataclass(frozen=True)
class JiraTeamArtifact:
    """Parsed `jira_metrics/individual.py --csv` output for one team or source."""

    name: str
    source_path: Path
    months: tuple[str, ...]
    points_by_assignee: dict[str, dict[str, int]]
    tickets_by_assignee: dict[str, dict[str, int]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source_path": str(self.source_path),
            "months": list(self.months),
            "points_by_assignee": self.points_by_assignee,
            "tickets_by_assignee": self.tickets_by_assignee,
        }


@dataclass(frozen=True)
class JiraTeamSummary:
    """Comparable team-level Jira throughput metrics."""

    name: str
    monthly_points: dict[str, int]
    monthly_tickets: dict[str, int]
    points_by_assignee: dict[str, dict[str, int]]
    tickets_by_assignee: dict[str, dict[str, int]]
    baseline_avg_points: float
    focus_avg_points: float
    baseline_avg_tickets: float
    focus_avg_tickets: float
    baseline_points_per_ticket: float
    focus_points_per_ticket: float
    first_focus_month: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "monthly_points": self.monthly_points,
            "monthly_tickets": self.monthly_tickets,
            "points_by_assignee": self.points_by_assignee,
            "tickets_by_assignee": self.tickets_by_assignee,
            "baseline_avg_points": self.baseline_avg_points,
            "focus_avg_points": self.focus_avg_points,
            "baseline_avg_tickets": self.baseline_avg_tickets,
            "focus_avg_tickets": self.focus_avg_tickets,
            "baseline_points_per_ticket": self.baseline_points_per_ticket,
            "focus_points_per_ticket": self.focus_points_per_ticket,
            "first_focus_month": self.first_focus_month,
        }


@dataclass(frozen=True)
class JiraSummary:
    """All-team and per-team Jira summary objects."""

    all_team_monthly_points: dict[str, int]
    all_team_monthly_tickets: dict[str, int]
    baseline_avg_points: float
    focus_avg_points: float
    baseline_avg_tickets: float
    focus_avg_tickets: float
    baseline_points_per_ticket: float
    focus_points_per_ticket: float
    teams: tuple[JiraTeamSummary, ...]
    source_artifacts: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "all_team_monthly_points": self.all_team_monthly_points,
            "all_team_monthly_tickets": self.all_team_monthly_tickets,
            "baseline_avg_points": self.baseline_avg_points,
            "focus_avg_points": self.focus_avg_points,
            "baseline_avg_tickets": self.baseline_avg_tickets,
            "focus_avg_tickets": self.focus_avg_tickets,
            "baseline_points_per_ticket": self.baseline_points_per_ticket,
            "focus_points_per_ticket": self.focus_points_per_ticket,
            "teams": [team.to_dict() for team in self.teams],
            "source_artifacts": list(self.source_artifacts),
        }


@dataclass(frozen=True)
class SheetSection:
    """A single bounded table destined for one sheet/tab."""

    title: str
    values: list[list[Any]]
    notes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "values": self.values,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class SheetPayload:
    """Final combined spreadsheet payload for the MCP layer."""

    tabs: tuple[str, ...]
    data: tuple[dict[str, Any], ...]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "tabs": list(self.tabs),
            "data": list(self.data),
            "metadata": self.metadata,
        }
