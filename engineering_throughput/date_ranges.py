"""Date range helpers for runtime year-agnostic throughput comparisons."""

from __future__ import annotations

from datetime import date, timedelta

from engineering_throughput.models import DateWindowConfig


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _month_end(value: date) -> date:
    if value.month == 12:
        return value.replace(month=12, day=31)
    return value.replace(month=value.month + 1, day=1) - timedelta(days=1)


def _month_labels(start: date, end: date) -> tuple[str, ...]:
    current = _month_start(start)
    labels: list[str] = []
    while current <= end:
        labels.append(current.strftime("%Y-%m"))
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1, day=1)
        else:
            current = current.replace(month=current.month + 1, day=1)
    return tuple(labels)


def _focus_label(focus_year: int, focus_start: date, end: date) -> str:
    focus_year_start = date(focus_year, 1, 1)
    if focus_start == focus_year_start:
        return f"{focus_year} YTD"
    start_month = focus_start.strftime("%b")
    end_month = end.strftime("%b")
    if focus_start.month == end.month:
        return f"{focus_year} {start_month}"
    return f"{focus_year} {start_month}-{end_month}"


def _is_month_aligned_start(value: date) -> bool:
    return value.day == 1


def _is_valid_focus_end(value: date, current_day: date) -> bool:
    return value == current_day or value == _month_end(value)


def resolve_date_window(
    baseline_year: int | None = None,
    focus_year: int | None = None,
    focus_start: date | None = None,
    date_end: date | None = None,
    today: date | None = None,
) -> DateWindowConfig:
    """Resolve the canonical comparison window.

    Defaults:
    - baseline year: previous calendar year
    - focus year: current calendar year
    - focus start: January 1 of the focus year
    - date end: today
    """

    current_day = today or date.today()
    resolved_focus_year = focus_year or current_day.year
    resolved_baseline_year = baseline_year or (resolved_focus_year - 1)
    resolved_end = date_end or current_day
    resolved_focus_start = focus_start or date(resolved_focus_year, 1, 1)
    start = date(resolved_baseline_year, 1, 1)

    if resolved_focus_start.year != resolved_focus_year:
        raise ValueError("--focus-start must be inside the focus year")
    if resolved_end < resolved_focus_start:
        raise ValueError("--date-end must be on or after --focus-start")
    if resolved_end.year != resolved_focus_year:
        raise ValueError("--date-end must be inside the focus year")
    if resolved_baseline_year >= resolved_focus_year:
        raise ValueError("--baseline-year must be earlier than --focus-year")
    if not _is_month_aligned_start(resolved_focus_start):
        raise ValueError("--focus-start must be the first day of a month")
    if not _is_valid_focus_end(resolved_end, current_day):
        raise ValueError("--date-end must be today or the last day of a month")

    baseline_end = date(resolved_baseline_year, 12, 31)
    baseline_months = _month_labels(start, baseline_end)
    focus_months = _month_labels(resolved_focus_start, resolved_end)
    all_months = _month_labels(start, resolved_end)
    baseline_label = f"{resolved_baseline_year} baseline"
    focus_label = _focus_label(resolved_focus_year, resolved_focus_start, resolved_end)

    return DateWindowConfig(
        baseline_year=resolved_baseline_year,
        focus_year=resolved_focus_year,
        start=start,
        end=resolved_end,
        focus_start=resolved_focus_start,
        baseline_months=baseline_months,
        focus_months=focus_months,
        all_months=all_months,
        baseline_label=baseline_label,
        focus_label=focus_label,
        comparison_label=f"{baseline_label} vs {focus_label}",
    )
