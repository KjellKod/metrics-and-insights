"""Generic GitHub throughput summarization and exclusion-aware process metrics."""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from engineering_throughput.models import ExcludeConfig, GitHubSummary, PeriodMetrics, ProcessEligibilityResult, RunConfig


def _iso_to_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _median(values: list[float | int | None]) -> float | None:
    cleaned = [float(value) for value in values if value is not None]
    if not cleaned:
        return None
    return round(statistics.median(cleaned), 2)


def _rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round((numerator / denominator) * 100, 1)


def _round(value: float | int | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    result = round(float(value), digits)
    if result.is_integer():
        return float(int(result))
    return result


def _period_rows(rows: list[dict[str, Any]], labels: tuple[str, ...]) -> list[dict[str, Any]]:
    label_set = set(labels)
    return [row for row in rows if row["month"] in label_set]


def _period_metrics(rows: list[dict[str, Any]], labels: tuple[str, ...]) -> PeriodMetrics:
    selected = _period_rows(rows, labels)
    count = len(selected)
    large_count = sum(1 for row in selected if row["large_pr"])
    slow_count = sum(1 for row in selected if row["slow_merge"])
    no_approval_count = sum(1 for row in selected if row["no_approval"])
    return PeriodMetrics(
        pr_avg_per_month=round(count / len(labels), 2) if labels else 0.0,
        median_merge_hours=_median([row["hours_to_merge"] for row in selected]),
        median_first_review_hours=_median([row["hours_to_first_review"] for row in selected]),
        median_first_approval_hours=_median([row["hours_to_first_approval"] for row in selected]),
        median_lines_changed=_median([row["lines_changed"] for row in selected]),
        large_pr_count=large_count,
        slow_merge_count=slow_count,
        no_approval_count=no_approval_count,
        large_pr_rate=_rate(large_count, count),
        slow_merge_rate=_rate(slow_count, count),
        no_approval_rate=_rate(no_approval_count, count),
        pr_count=count,
    )


def _matches_rule(row: dict[str, Any], rule: Any) -> bool:
    merged_at = _iso_to_datetime(row["merged_at"])
    if merged_at is None:
        return False
    merged_date = merged_at.date()
    if rule.start and merged_date < rule.start:
        return False
    if rule.end and merged_date > rule.end:
        return False
    if rule.repos and row["repo"].lower() not in {repo.lower() for repo in rule.repos}:
        return False
    if rule.authors and row["author"].lower() not in {author.lower() for author in rule.authors}:
        return False
    if rule.title_contains:
        title = row["title"].lower()
        if not any(term in title for term in rule.title_contains):
            return False
    return True


def build_process_eligibility(rows: list[dict[str, Any]], exclusions: ExcludeConfig) -> ProcessEligibilityResult:
    """Partition raw rows into eligible vs excluded process metrics."""

    eligible_rows: list[dict[str, Any]] = []
    excluded_rows: list[dict[str, Any]] = []
    reason_counts: Counter[str] = Counter()
    for row in rows:
        reasons: list[str] = []
        merged_at = _iso_to_datetime(row["merged_at"])
        merged_date = merged_at.date() if merged_at else None

        for window in exclusions.windows:
            if merged_date and window.start <= merged_date <= window.end:
                reasons.append(window.name)

        for rule in exclusions.rules:
            if _matches_rule(row, rule):
                reasons.append(rule.reason)

        if reasons:
            excluded = dict(row)
            excluded["exclusion_reasons"] = sorted(set(reasons))
            excluded_rows.append(excluded)
            reason_counts.update(excluded["exclusion_reasons"])
        else:
            eligible_rows.append(dict(row))

    return ProcessEligibilityResult(
        eligible_rows=tuple(eligible_rows),
        excluded_rows=tuple(excluded_rows),
        reason_counts=dict(sorted(reason_counts.items())),
    )


def _monthly_trend(
    raw_rows: list[dict[str, Any]],
    eligible_rows: list[dict[str, Any]],
    excluded_rows: list[dict[str, Any]],
    all_months: tuple[str, ...],
) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for label in all_months:
        raw_month = [row for row in raw_rows if row["month"] == label]
        eligible_month = [row for row in eligible_rows if row["month"] == label]
        excluded_month = [row for row in excluded_rows if row["month"] == label]
        metric = _period_metrics(eligible_month, (label,))
        rows.append(
            {
                "month": label,
                "raw_pr_count": len(raw_month),
                "eligible_pr_count": len(eligible_month),
                "excluded_pr_count": len(excluded_month),
                "median_merge_hours": metric.median_merge_hours,
                "median_first_approval_hours": metric.median_first_approval_hours,
                "median_lines_changed": metric.median_lines_changed,
                "large_pr_rate": metric.large_pr_rate,
                "slow_merge_rate": metric.slow_merge_rate,
                "no_approval_rate": metric.no_approval_rate,
            }
        )
    return tuple(rows)


def _repo_comparison(
    raw_rows: list[dict[str, Any]],
    eligible_rows: list[dict[str, Any]],
    baseline_months: tuple[str, ...],
    focus_months: tuple[str, ...],
) -> tuple[dict[str, Any], ...]:
    repos = sorted({row["repo"] for row in raw_rows})
    output: list[dict[str, Any]] = []
    for repo in repos:
        raw_repo_rows = [row for row in raw_rows if row["repo"] == repo]
        eligible_repo_rows = [row for row in eligible_rows if row["repo"] == repo]
        raw_baseline = _period_metrics(raw_repo_rows, baseline_months)
        raw_focus = _period_metrics(raw_repo_rows, focus_months)
        eligible_baseline = _period_metrics(eligible_repo_rows, baseline_months)
        eligible_focus = _period_metrics(eligible_repo_rows, focus_months)
        output.append(
            {
                "repo": repo,
                "baseline_raw_pr_avg": raw_baseline.pr_avg_per_month,
                "focus_raw_pr_avg": raw_focus.pr_avg_per_month,
                "raw_pr_avg_delta": round(raw_focus.pr_avg_per_month - raw_baseline.pr_avg_per_month, 2),
                "baseline_merge_hours": eligible_baseline.median_merge_hours,
                "focus_merge_hours": eligible_focus.median_merge_hours,
                "baseline_large_pr_rate": eligible_baseline.large_pr_rate,
                "focus_large_pr_rate": eligible_focus.large_pr_rate,
                "baseline_slow_merge_rate": eligible_baseline.slow_merge_rate,
                "focus_slow_merge_rate": eligible_focus.slow_merge_rate,
                "focus_no_approval_count": eligible_focus.no_approval_count,
            }
        )
    output.sort(key=lambda row: (row["focus_raw_pr_avg"], row["raw_pr_avg_delta"], row["repo"]), reverse=True)
    return tuple(output)


def _author_comparison(
    raw_rows: list[dict[str, Any]],
    eligible_rows: list[dict[str, Any]],
    baseline_months: tuple[str, ...],
    focus_months: tuple[str, ...],
) -> tuple[dict[str, Any], ...]:
    authors = sorted({row["author"] for row in raw_rows})
    output: list[dict[str, Any]] = []
    for author in authors:
        raw_author_rows = [row for row in raw_rows if row["author"] == author]
        eligible_author_rows = [row for row in eligible_rows if row["author"] == author]
        raw_baseline = _period_metrics(raw_author_rows, baseline_months)
        raw_focus = _period_metrics(raw_author_rows, focus_months)
        if raw_baseline.pr_count == 0 and raw_focus.pr_count == 0:
            continue
        eligible_baseline = _period_metrics(eligible_author_rows, baseline_months)
        eligible_focus = _period_metrics(eligible_author_rows, focus_months)
        output.append(
            {
                "author": author,
                "baseline_raw_pr_avg": raw_baseline.pr_avg_per_month,
                "focus_raw_pr_avg": raw_focus.pr_avg_per_month,
                "raw_pr_avg_delta": round(raw_focus.pr_avg_per_month - raw_baseline.pr_avg_per_month, 2),
                "baseline_merge_hours": eligible_baseline.median_merge_hours,
                "focus_merge_hours": eligible_focus.median_merge_hours,
                "baseline_large_pr_rate": eligible_baseline.large_pr_rate,
                "focus_large_pr_rate": eligible_focus.large_pr_rate,
                "baseline_no_approval_rate": eligible_baseline.no_approval_rate,
                "focus_no_approval_rate": eligible_focus.no_approval_rate,
            }
        )
    output.sort(key=lambda row: (row["focus_raw_pr_avg"], row["raw_pr_avg_delta"], row["author"]), reverse=True)
    return tuple(output[:25])


def _author_monthly(eligible_rows: list[dict[str, Any]], all_months: tuple[str, ...]) -> tuple[dict[str, Any], ...]:
    author_counts: Counter[str] = Counter(row["author"] for row in eligible_rows)
    top_authors = [author for author, _count in author_counts.most_common(10)]
    monthly_counts: Counter[tuple[str, str]] = Counter((row["month"], row["author"]) for row in eligible_rows)
    return tuple(
        {
            "month": month,
            "counts": {author: monthly_counts[(month, author)] for author in top_authors},
        }
        for month in all_months
    )


def _flagged_authors(eligible_rows: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    by_author: dict[str, dict[str, int]] = defaultdict(
        lambda: {"flagged_prs": 0, "large_prs": 0, "slow_merges": 0, "no_approval_prs": 0}
    )
    for row in eligible_rows:
        if not (row["large_pr"] or row["slow_merge"] or row["no_approval"]):
            continue
        metrics = by_author[row["author"]]
        metrics["flagged_prs"] += 1
        metrics["large_prs"] += int(row["large_pr"])
        metrics["slow_merges"] += int(row["slow_merge"])
        metrics["no_approval_prs"] += int(row["no_approval"])
    output = [{"author": author, **metrics} for author, metrics in by_author.items()]
    output.sort(
        key=lambda row: (row["no_approval_prs"], row["large_prs"], row["slow_merges"], row["flagged_prs"], row["author"]),
        reverse=True,
    )
    return tuple(output[:25])


def _flagged_pr_sample(eligible_rows: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    flagged = [row for row in eligible_rows if row["large_pr"] or row["slow_merge"] or row["no_approval"]]
    flagged.sort(
        key=lambda row: (
            int(row["no_approval"]),
            int(row["large_pr"]),
            row["lines_changed"],
            row["hours_to_merge"] or 0,
            row["repo"],
            row["pr_number"],
        ),
        reverse=True,
    )
    return tuple(flagged[:40])


def _no_approval_audit(eligible_rows: list[dict[str, Any]], excluded_rows: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    audit: list[dict[str, Any]] = []
    for row in eligible_rows:
        if row["no_approval"]:
            audit.append(
                {
                    "month": row["month"],
                    "repo": row["repo"],
                    "pr_number": row["pr_number"],
                    "author": row["author"],
                    "title": row["title"],
                    "status": "counted",
                    "reason": "",
                }
            )
    for row in excluded_rows:
        if row["no_approval"]:
            audit.append(
                {
                    "month": row["month"],
                    "repo": row["repo"],
                    "pr_number": row["pr_number"],
                    "author": row["author"],
                    "title": row["title"],
                    "status": "excluded",
                    "reason": ", ".join(row.get("exclusion_reasons", [])),
                }
            )
    audit.sort(key=lambda row: (row["status"], row["month"], row["repo"], row["pr_number"]))
    return tuple(audit)


def summarize_github_rows(rows: list[dict[str, Any]], config: RunConfig) -> GitHubSummary:
    """Summarize raw GitHub rows into payload-ready comparison objects."""

    eligibility = build_process_eligibility(rows, config.exclude_config)
    eligible_rows = list(eligibility.eligible_rows)
    excluded_rows = list(eligibility.excluded_rows)
    baseline_months = config.date_window.baseline_months
    focus_months = config.date_window.focus_months

    return GitHubSummary(
        raw_baseline=_period_metrics(rows, baseline_months),
        raw_focus=_period_metrics(rows, focus_months),
        eligible_baseline=_period_metrics(eligible_rows, baseline_months),
        eligible_focus=_period_metrics(eligible_rows, focus_months),
        monthly_trend=_monthly_trend(rows, eligible_rows, excluded_rows, config.date_window.all_months),
        repo_comparison=_repo_comparison(rows, eligible_rows, baseline_months, focus_months),
        author_comparison=_author_comparison(rows, eligible_rows, baseline_months, focus_months),
        author_monthly=_author_monthly(eligible_rows, config.date_window.all_months),
        flagged_authors=_flagged_authors(eligible_rows),
        flagged_pr_sample=_flagged_pr_sample(eligible_rows),
        no_approval_audit=_no_approval_audit(eligible_rows, excluded_rows),
        exclusion_reason_counts=eligibility.reason_counts,
        eligible_rows=tuple(eligible_rows),
        excluded_rows=tuple(excluded_rows),
    )
