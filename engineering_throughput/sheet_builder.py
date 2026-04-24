"""Assemble bounded Google Sheets payloads from sheet sections."""

from __future__ import annotations

from typing import Any

from engineering_throughput.models import SheetPayload, SheetSection


def _column_label(index: int) -> str:
    result = ""
    current = index
    while current > 0:
        current, remainder = divmod(current - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _normalize_values(values: list[list[Any]]) -> list[list[Any]]:
    if not values:
        return [[""]]
    width = max(len(row) for row in values) if values else 1
    width = max(width, 1)
    return [row + [""] * (width - len(row)) for row in values]


def _bounded_range(title: str, values: list[list[Any]]) -> str:
    row_count = len(values)
    column_count = len(values[0])
    escaped_title = title.replace("'", "''")
    return f"'{escaped_title}'!A1:{_column_label(column_count)}{row_count}"


def assemble_sheet_payload(sections: list[SheetSection], metadata: dict[str, Any] | None = None) -> SheetPayload:
    """Build a single combined spreadsheet payload from all sections."""

    data: list[dict[str, Any]] = []
    tabs: list[str] = []
    seen_titles: dict[str, str] = {}
    for section in sections:
        normalized_title = section.title.lower()
        if normalized_title in seen_titles:
            raise ValueError(f"Duplicate sheet title: {section.title}")
        seen_titles[normalized_title] = section.title
        normalized = _normalize_values(section.values)
        tabs.append(section.title)
        data.append({"tab": section.title, "range": _bounded_range(section.title, normalized), "values": normalized})
    return SheetPayload(tabs=tuple(tabs), data=tuple(data), metadata=metadata or {})
