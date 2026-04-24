"""Payload builders for GitHub throughput tabs."""

from __future__ import annotations

from typing import Any

from engineering_throughput.models import DateWindowConfig, GitHubSummary, SheetSection

MAX_NO_APPROVAL_AUDIT_ROWS = 40
MAX_FLAGGED_PR_SAMPLE_ROWS = 30
MAX_AUTHOR_ROWS = 25


def _render_value(value: Any) -> Any:
    if value is None:
        return ""
    return value


def _metric_rows(summary: GitHubSummary) -> list[list[Any]]:
    raw_baseline = summary.raw_baseline.to_dict()
    raw_focus = summary.raw_focus.to_dict()
    eligible_baseline = summary.eligible_baseline.to_dict()
    eligible_focus = summary.eligible_focus.to_dict()
    metrics = [
        ("Merged PRs per month", "pr_avg_per_month"),
        ("Merged PR count", "pr_count"),
        ("Median hours to merge", "median_merge_hours"),
        ("Median hours to first approval", "median_first_approval_hours"),
        ("Median lines changed", "median_lines_changed"),
        ("Large PR rate %", "large_pr_rate"),
        ("Slow merge rate %", "slow_merge_rate"),
        ("No approval rate %", "no_approval_rate"),
    ]
    rows = [["Metric", "Baseline raw", "Focus raw", "Baseline eligible", "Focus eligible"]]
    for label, key in metrics:
        rows.append(
            [
                label,
                _render_value(raw_baseline[key]),
                _render_value(raw_focus[key]),
                _render_value(eligible_baseline[key]),
                _render_value(eligible_focus[key]),
            ]
        )
    return rows


def build_github_sections(summary: GitHubSummary, date_window: DateWindowConfig) -> list[SheetSection]:
    """Build all GitHub sheet sections from a summarized result."""

    trend_rows = [["Month", "Raw PRs", "Eligible PRs", "Excluded PRs", "Median merge hrs", "Median first approval hrs", "Median lines", "Large PR rate %", "Slow merge rate %", "No approval rate %"]]
    for row in summary.monthly_trend:
        trend_rows.append(
            [
                row["month"],
                row["raw_pr_count"],
                row["eligible_pr_count"],
                row["excluded_pr_count"],
                _render_value(row["median_merge_hours"]),
                _render_value(row["median_first_approval_hours"]),
                _render_value(row["median_lines_changed"]),
                row["large_pr_rate"],
                row["slow_merge_rate"],
                row["no_approval_rate"],
            ]
        )

    summary_values = [
        ["GitHub Summary"],
        ["Comparison", date_window.comparison_label],
        [],
    ] + _metric_rows(summary) + [[""], ["Monthly trend"]] + trend_rows

    reason_rows = [["Reason", "Excluded PR count"]]
    if summary.exclusion_reason_counts:
        for reason, count in summary.exclusion_reason_counts.items():
            reason_rows.append([reason, count])
    else:
        reason_rows.append(["none", 0])

    audit_rows = [["Month", "Repo", "PR", "Author", "Status", "Reason", "Title"]]
    for row in summary.no_approval_audit[:MAX_NO_APPROVAL_AUDIT_ROWS]:
        audit_rows.append(
            [row["month"], row["repo"], row["pr_number"], row["author"], row["status"], row["reason"], row["title"]]
        )
    if len(summary.no_approval_audit) > MAX_NO_APPROVAL_AUDIT_ROWS:
        audit_rows.append(["...", "", "", "", "", "", f"{len(summary.no_approval_audit) - MAX_NO_APPROVAL_AUDIT_ROWS} additional rows kept locally"])

    repo_rows = [["Repo", "Baseline raw PR avg", "Focus raw PR avg", "Raw PR avg delta", "Baseline merge hrs", "Focus merge hrs", "Baseline large PR rate %", "Focus large PR rate %", "Baseline slow merge rate %", "Focus slow merge rate %", "Focus no approval count"]]
    for row in summary.repo_comparison:
        repo_rows.append(
            [
                row["repo"],
                row["baseline_raw_pr_avg"],
                row["focus_raw_pr_avg"],
                row["raw_pr_avg_delta"],
                _render_value(row["baseline_merge_hours"]),
                _render_value(row["focus_merge_hours"]),
                row["baseline_large_pr_rate"],
                row["focus_large_pr_rate"],
                row["baseline_slow_merge_rate"],
                row["focus_slow_merge_rate"],
                row["focus_no_approval_count"],
            ]
        )

    author_rows = [["Author", "Baseline raw PR avg", "Focus raw PR avg", "Raw PR avg delta", "Baseline merge hrs", "Focus merge hrs", "Baseline large PR rate %", "Focus large PR rate %", "Baseline no approval rate %", "Focus no approval rate %"]]
    for row in summary.author_comparison[:MAX_AUTHOR_ROWS]:
        author_rows.append(
            [
                row["author"],
                row["baseline_raw_pr_avg"],
                row["focus_raw_pr_avg"],
                row["raw_pr_avg_delta"],
                _render_value(row["baseline_merge_hours"]),
                _render_value(row["focus_merge_hours"]),
                row["baseline_large_pr_rate"],
                row["focus_large_pr_rate"],
                row["baseline_no_approval_rate"],
                row["focus_no_approval_rate"],
            ]
        )

    monthly_author_rows = [["Month"]]
    if summary.author_monthly:
        top_authors = list(summary.author_monthly[0]["counts"].keys())
        monthly_author_rows[0].extend(top_authors)
        for row in summary.author_monthly:
            monthly_author_rows.append([row["month"]] + [row["counts"][author] for author in top_authors])

    flag_author_rows = [["Author", "Flagged PRs", "Large PRs", "Slow merges", "No approval PRs"]]
    for row in summary.flagged_authors:
        flag_author_rows.append(
            [row["author"], row["flagged_prs"], row["large_prs"], row["slow_merges"], row["no_approval_prs"]]
        )

    sample_rows = [["Month", "Repo", "PR", "Author", "Hours to merge", "Lines changed", "Large PR", "Slow merge", "No approval", "Title", "URL"]]
    for row in summary.flagged_pr_sample[:MAX_FLAGGED_PR_SAMPLE_ROWS]:
        sample_rows.append(
            [
                row["month"],
                row["repo"],
                row["pr_number"],
                row["author"],
                _render_value(row["hours_to_merge"]),
                row["lines_changed"],
                "TRUE" if row["large_pr"] else "FALSE",
                "TRUE" if row["slow_merge"] else "FALSE",
                "TRUE" if row["no_approval"] else "FALSE",
                row["title"],
                row["url"],
            ]
        )
    if len(summary.flagged_pr_sample) > MAX_FLAGGED_PR_SAMPLE_ROWS:
        sample_rows.append(["...", "", "", "", "", "", "", "", "", f"{len(summary.flagged_pr_sample) - MAX_FLAGGED_PR_SAMPLE_ROWS} additional rows kept locally", ""])

    return [
        SheetSection(title="GitHub Summary", values=summary_values),
        SheetSection(
            title="GitHub No Approval",
            values=[["GitHub No Approval"], [], ["Excluded reasons"]] + reason_rows + [[""], ["Audit"]] + audit_rows,
        ),
        SheetSection(title="GitHub Repos", values=[["GitHub Repos"], []] + repo_rows),
        SheetSection(
            title="GitHub Authors",
            values=[["GitHub Authors"], []] + author_rows + [[""], ["Top authors by month"]] + monthly_author_rows,
        ),
        SheetSection(
            title="GitHub Flags",
            values=[["GitHub Flags"], [], ["Flagged authors"]] + flag_author_rows + [[""], ["Flagged PR sample"]] + sample_rows,
        ),
    ]
