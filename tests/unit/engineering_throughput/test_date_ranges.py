from __future__ import annotations

from datetime import date

import pytest

from engineering_throughput.date_ranges import resolve_date_window


def test_default_window_uses_previous_year_and_current_year() -> None:
    window = resolve_date_window(today=date(2026, 4, 23))

    assert window.baseline_year == 2025
    assert window.focus_year == 2026
    assert window.start == date(2025, 1, 1)
    assert window.end == date(2026, 4, 23)
    assert window.focus_start == date(2026, 1, 1)


def test_generated_labels_support_ytd_and_partial_focus_ranges() -> None:
    ytd_window = resolve_date_window(today=date(2026, 4, 23))
    assert ytd_window.focus_label == "2026 YTD"

    partial_window = resolve_date_window(
        baseline_year=2025,
        focus_year=2026,
        focus_start=date(2026, 2, 1),
        date_end=date(2026, 4, 23),
        today=date(2026, 4, 23),
    )
    assert partial_window.focus_label == "2026 Feb-Apr"
    assert partial_window.comparison_label == "2025 baseline vs 2026 Feb-Apr"
    assert "2025 vs 2026" not in partial_window.comparison_label


def test_focus_window_requires_month_aligned_start_and_month_end_or_today() -> None:
    with pytest.raises(ValueError, match="--focus-start must be the first day of a month"):
        resolve_date_window(
            baseline_year=2025,
            focus_year=2026,
            focus_start=date(2026, 2, 15),
            date_end=date(2026, 3, 31),
            today=date(2026, 4, 23),
        )

    with pytest.raises(ValueError, match="--date-end must be today or the last day of a month"):
        resolve_date_window(
            baseline_year=2025,
            focus_year=2026,
            focus_start=date(2026, 2, 1),
            date_end=date(2026, 3, 15),
            today=date(2026, 4, 23),
        )
