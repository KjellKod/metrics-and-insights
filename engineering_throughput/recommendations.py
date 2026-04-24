"""Generic recommendation generation for engineering throughput outputs."""

from __future__ import annotations

from engineering_throughput.models import DateWindowConfig, GitHubSummary, JiraSummary, SheetSection, TeamConfig


def _priority(flag: bool) -> str:
    return "A" if flag else "B"


def _display_optional_number(value: float | None) -> str:
    return "n/a" if value is None else str(value)


def build_recommendations(
    jira_summary: JiraSummary,
    github_summary: GitHubSummary,
    team_config: tuple[TeamConfig, ...],
    date_window: DateWindowConfig,
) -> SheetSection:
    """Build generic, data-driven recommendations without embedded org prose."""

    rows = [
        ["Recommendations"],
        ["Audience", "Observation", "Evidence", "Suggested action", "Priority"],
    ]

    raw_throughput_up = github_summary.raw_focus.pr_avg_per_month >= github_summary.raw_baseline.pr_avg_per_month
    large_pr_worse = github_summary.eligible_focus.large_pr_rate > github_summary.eligible_baseline.large_pr_rate
    baseline_approval = github_summary.eligible_baseline.median_first_approval_hours
    focus_approval = github_summary.eligible_focus.median_first_approval_hours
    approval_worse = baseline_approval is not None and focus_approval is not None and focus_approval > baseline_approval

    rows.append(
        [
            "Engineering leaders",
            "Throughput is rising faster than the surrounding review process." if raw_throughput_up else "Throughput is below the baseline comparison.",
            f"GitHub merged PRs/month: {github_summary.raw_baseline.pr_avg_per_month} -> {github_summary.raw_focus.pr_avg_per_month}.",
            "Keep delivery speed gains, but tighten review ownership and slice work into smaller units.",
            _priority(raw_throughput_up),
        ]
    )
    rows.append(
        [
            "Tech leads",
            "PR batching is increasing process risk." if large_pr_worse else "PR size is stable or improving.",
            f"Large PR rate: {github_summary.eligible_baseline.large_pr_rate}% -> {github_summary.eligible_focus.large_pr_rate}%.",
            "Use split plans or smaller acceptance slices before review when a change grows beyond normal size.",
            _priority(large_pr_worse),
        ]
    )
    rows.append(
        [
            "Managers",
            "Human approval latency is the next visible constraint." if approval_worse else "Approval latency held steady or improved.",
            f"Median first approval hours: {_display_optional_number(baseline_approval)} -> {_display_optional_number(focus_approval)}.",
            "Review the queue daily and set a same-business-day target for small PRs.",
            _priority(approval_worse),
        ]
    )
    rows.append(
        [
            "Managers and PMs",
            "Jira output should be interpreted with GitHub reviewability, not alone.",
            f"Completed points/mo: {jira_summary.baseline_avg_points} -> {jira_summary.focus_avg_points}; completed tickets/mo: {jira_summary.baseline_avg_tickets} -> {jira_summary.focus_avg_tickets}.",
            "Pair throughput goals with reviewability goals such as PR size, first approval latency, and exception labeling.",
            "B",
        ]
    )

    if team_config:
        rows.extend([[""], ["Team", "Observation", "Evidence", "Suggested action", "Priority"]])
        team_summaries = {team.name: team for team in jira_summary.teams}
        for team in team_config:
            team_summary = team_summaries.get(team.name)
            if team_summary is None:
                continue
            focus_up = team_summary.focus_avg_points >= team_summary.baseline_avg_points
            rows.append(
                [
                    team.name,
                    "Team output improved over the baseline period." if focus_up else "Team output is below the baseline period.",
                    f"Completed points/mo: {team_summary.baseline_avg_points} -> {team_summary.focus_avg_points}; completed tickets/mo: {team_summary.baseline_avg_tickets} -> {team_summary.focus_avg_tickets}.",
                    "Preserve what is working when output is up; when output is down, inspect work mix, WIP, and review queue health before drawing performance conclusions.",
                    _priority(not focus_up),
                ]
            )

    rows.extend(
        [
            [""],
            ["Experiment", "Why", "How to measure", "Owner", "Priority"],
            ["Small-PR lane", "Reviewability becomes the constraint as implementation speed rises.", "Large PR rate and median lines changed.", "Tech leads", "A"],
            ["Explicit exception labels", "No-approval data is only useful when exceptions are auditable.", "Share of counted vs excluded no-approval PRs.", "Managers", "A"],
            ["Weekly flow review", "Throughput and review queues drift faster than sprint-only rituals catch.", "Open PR age, approval latency, and carried WIP.", "Managers and PMs", "B"],
        ]
    )

    return SheetSection(title="Recommendations", values=rows, notes={"comparison": date_window.comparison_label})
