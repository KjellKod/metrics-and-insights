#!/usr/bin/env python3
"""Report selected Jira ticket delivery time by completion month."""

# pylint: disable=import-error,too-many-lines,too-many-instance-attributes

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Sequence

from cycle_time import HOURS_TO_DAYS, SECONDS_TO_HOURS, business_time_spent_in_seconds
from jira_utils import (
    ChangelogFetchResult,
    JiraSearchResult,
    fetch_complete_changelogs,
    get_completion_statuses,
    search_jira_issues_raw,
)


CANDIDATE_CUSHION_DAYS = 2
CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
SUMMARY_COLUMNS = (
    "Month",
    "Completed Tickets",
    "Completed Cycles",
    "Reopened Cycles",
    "Measured Cycles",
    "Cycles Missing Start",
    "Tickets With Missing Start",
    "Total Business Cycle Days",
    "Median Business Cycle Days per Ticket",
    "P85 Business Cycle Days per Ticket",
    "Data Complete",
)
DETAIL_COLUMNS = (
    "Issue Key",
    "Issue ID",
    "Issue Type at Latest Completion",
    "Latest Matching Completion",
    "Completion Month",
    "Matched Label",
    "Matched Field Value",
    "Completed Cycles",
    "Reopened Cycles",
    "Measured Cycles",
    "Cycles Missing Start",
    "Total Business Cycle Days",
    "Cycle Evidence",
)


class ReportError(RuntimeError):
    """An actionable fatal report error."""


@dataclass(frozen=True)
class ReportConfig:
    year: int
    issue_types: frozenset[str]
    start_statuses: frozenset[str]
    end_statuses: frozenset[str]
    label: str | None
    field_id: str | None
    field_value: str | None
    projects: tuple[str, ...] | None
    output_dir: Path
    write_csv: bool


@dataclass(frozen=True)
class StatusEvent:
    timestamp: datetime
    from_status: str
    to_status: str
    history_id: str


@dataclass(frozen=True)
class FieldEvent:
    timestamp: datetime
    field_name: str
    field_id: str
    from_value: Any
    from_string: Any
    to_value: Any
    to_string: Any
    history_id: str


@dataclass(frozen=True)
class SelectorSnapshot:
    labels: frozenset[str]
    field_value: str
    issue_type: str


@dataclass(frozen=True)
class CycleResult:
    completion_timestamp: datetime
    started_at: datetime | None
    business_seconds: float
    missing_start: bool
    reopened: bool


@dataclass(frozen=True)
class TicketResult:
    issue_key: str
    issue_id: str
    latest_completion: datetime
    latest_issue_type: str
    matched_label: str
    matched_field_value: str
    completed_cycles: int
    reopened_cycles: int
    measured_cycles: int
    missing_start_cycles: int
    total_business_seconds: float
    cycle_evidence: tuple[str, ...]

    @property
    def total_business_days(self) -> float:
        return self.total_business_seconds / (SECONDS_TO_HOURS * HOURS_TO_DAYS)


@dataclass(frozen=True)
class SummaryRow:
    month: str
    completed_tickets: int
    completed_cycles: int
    reopened_cycles: int
    measured_cycles: int
    missing_start_cycles: int
    tickets_with_missing_start: int
    total_business_days: float
    median_business_days: float
    p85_business_days: float
    data_complete: bool = True


def parse_csv_values(value: str, option_name: str) -> list[str]:
    values = [item.strip() for item in value.split(",")]
    if not values or any(not item for item in values):
        raise argparse.ArgumentTypeError(f"{option_name} must not contain empty values")
    return values


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Measure active Jira delivery time for tickets selected by historical label, "
            "custom field value, or both."
        )
    )
    parser.add_argument("--year", required=True, type=int, help="Completion year to report, for example 2026")
    parser.add_argument("--issue-types", required=True, help="Comma-separated issue types to include")
    parser.add_argument("--field-id-env", help="Environment variable containing the numeric custom field ID")
    parser.add_argument("--field-value", help="Custom field display value that must match at completion")
    parser.add_argument("--label", help="Label that must match at completion")
    parser.add_argument("--start-statuses", required=True, help="Comma-separated statuses that start a measured cycle")
    parser.add_argument(
        "--end-statuses",
        help="Comma-separated statuses that complete a measured cycle; defaults to COMPLETION_STATUSES",
    )
    parser.add_argument("--all-projects", action="store_true", help="Search all Jira projects visible to the account")
    parser.add_argument(
        "--output-dir",
        default="reports/filtered-delivery-time",
        type=Path,
        help="Directory for CSV output",
    )
    parser.add_argument("-csv", action="store_true", help="Write monthly summary and ticket detail CSV files")
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        args.issue_types = parse_csv_values(args.issue_types, "--issue-types")
        args.start_statuses = parse_csv_values(args.start_statuses, "--start-statuses")
        if args.end_statuses is not None:
            args.end_statuses = parse_csv_values(args.end_statuses, "--end-statuses")
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    if args.label is not None:
        args.label = args.label.strip()
        if not args.label:
            parser.error("--label must not be blank")
    if args.field_value is not None:
        args.field_value = args.field_value.strip()
        if not args.field_value:
            parser.error("--field-value must not be blank")
    if args.field_id_env is not None:
        args.field_id_env = args.field_id_env.strip()
        if not args.field_id_env:
            parser.error("--field-id-env must not be blank")
    if not args.label and not args.field_value:
        parser.error("at least one selector is required: --label or --field-value with --field-id-env")
    if bool(args.field_id_env) != bool(args.field_value):
        parser.error("--field-id-env and --field-value must be supplied together")
    return args


def _normalized_set(values: Sequence[str]) -> frozenset[str]:
    return frozenset(value.strip().casefold() for value in values if value.strip())


def resolve_projects(args: argparse.Namespace) -> tuple[str, ...] | None:
    if args.all_projects:
        return None
    raw = os.environ.get("JIRA_PROJECTS", "")
    projects = [project.strip() for project in raw.split(",") if project.strip()]
    if not projects:
        raise ReportError("JIRA_PROJECTS is required unless --all-projects is supplied")
    return tuple(projects)


def resolve_field_id(field_id_env: str | None) -> str | None:
    if field_id_env is None:
        return None
    raw = os.environ.get(field_id_env)
    if raw is None or not raw.strip():
        raise ReportError(f"{field_id_env} is required for --field-id-env")
    field_id = raw.strip()
    if not field_id.isdecimal():
        raise ReportError(f"{field_id_env} must contain a numeric Jira custom field ID")
    return field_id


def build_config(args: argparse.Namespace) -> ReportConfig:
    end_statuses = args.end_statuses or get_completion_statuses()
    field_id = resolve_field_id(args.field_id_env)
    return ReportConfig(
        year=args.year,
        issue_types=_normalized_set(args.issue_types),
        start_statuses=_normalized_set(args.start_statuses),
        end_statuses=_normalized_set(end_statuses),
        label=args.label.strip() if args.label else None,
        field_id=field_id,
        field_value=args.field_value.strip() if args.field_value else None,
        projects=resolve_projects(args),
        output_dir=args.output_dir,
        write_csv=args.csv,
    )


def _quote_jql(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_completion_candidate_jql(
    year: int, issue_types: frozenset[str], end_statuses: frozenset[str], projects: tuple[str, ...] | None
) -> str:
    start = datetime(year, 1, 1) - timedelta(days=CANDIDATE_CUSHION_DAYS)
    end = datetime(year, 12, 31) + timedelta(days=CANDIDATE_CUSHION_DAYS)
    clauses = [
        f"issueType in ({', '.join(_quote_jql(value) for value in sorted(issue_types))})",
        f"status CHANGED TO ({', '.join(_quote_jql(value) for value in sorted(end_statuses))}) "
        f'DURING ("{start:%Y-%m-%d}", "{end:%Y-%m-%d}")',
    ]
    if projects is not None:
        clauses.insert(0, f"project in ({', '.join(_quote_jql(project) for project in projects)})")
    return " AND ".join(clauses) + " ORDER BY updated ASC"


def candidate_fields(field_id: str | None) -> list[str]:
    fields = {"issuetype", "labels"}
    if field_id is not None:
        fields.add(f"customfield_{field_id}")
    return sorted(fields)


def parse_jira_timestamp(value: Any) -> datetime:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value) / 1000 if abs(float(value)) >= 100_000_000_000 else float(value)
        return datetime.fromtimestamp(seconds).astimezone()
    if not isinstance(value, str):
        raise ValueError("unsupported Jira timestamp")
    normalized = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Jira timestamp must include a UTC offset")
    return parsed


def _history_sort_key(history_id: str) -> tuple[int, int | str]:
    stripped = history_id.strip()
    if stripped.isdecimal():
        return (0, int(stripped))
    return (1, stripped.casefold())


def normalize_value(value: Any, string_value: Any = None) -> str:
    for candidate in (string_value, value):
        if isinstance(candidate, dict):
            for key in ("value", "name", "key", "id"):
                nested = candidate.get(key)
                if nested not in (None, ""):
                    return str(nested).strip()
        elif candidate not in (None, ""):
            return str(candidate).strip()
    return ""


def _split_label_value(value: Any, string_value: Any = None) -> frozenset[str]:
    raw = string_value if string_value not in (None, "") else value
    if raw in (None, ""):
        return frozenset()
    if isinstance(raw, list):
        return frozenset(str(item).strip() for item in raw if str(item).strip())
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return frozenset()
        separators = [",", " "]
        for separator in separators:
            parts = [part.strip() for part in text.split(separator) if part.strip()]
            if len(parts) > 1:
                return frozenset(parts)
        return frozenset({text})
    return frozenset({str(raw).strip()})


def normalize_changelog(histories: list[dict[str, Any]]) -> list[FieldEvent]:
    events: list[FieldEvent] = []
    for history in histories:
        history_id = str(history.get("id", ""))
        timestamp = parse_jira_timestamp(history.get("created"))
        items = history.get("items", [])
        if not isinstance(items, list):
            raise ReportError(f"Changelog history {history_id or '(unknown)'} had invalid items")
        for item in items:
            if not isinstance(item, dict):
                raise ReportError(f"Changelog history {history_id or '(unknown)'} had an invalid item")
            events.append(
                FieldEvent(
                    timestamp=timestamp,
                    field_name=str(item.get("field") or ""),
                    field_id=str(item.get("fieldId") or ""),
                    from_value=item.get("from"),
                    from_string=item.get("fromString"),
                    to_value=item.get("to"),
                    to_string=item.get("toString"),
                    history_id=history_id,
                )
            )
    events.sort(key=lambda event: (event.timestamp, _history_sort_key(event.history_id), event.field_id))
    return events


def _issue_fields(issue: dict[str, Any]) -> dict[str, Any]:
    fields = issue.get("fields")
    if not isinstance(fields, dict):
        raise ReportError(f"Issue {issue.get('key', '(unknown)')} did not include fields")
    return fields


def _current_labels(issue: dict[str, Any]) -> frozenset[str]:
    labels = _issue_fields(issue).get("labels", [])
    if not isinstance(labels, list):
        return frozenset()
    return frozenset(str(label).strip() for label in labels if str(label).strip())


def _current_issue_type(issue: dict[str, Any]) -> str:
    issue_type = _issue_fields(issue).get("issuetype", {})
    if isinstance(issue_type, dict):
        return str(issue_type.get("name") or "").strip()
    return ""


def _current_field_value(issue: dict[str, Any], field_id: str | None) -> str:
    if field_id is None:
        return ""
    return normalize_value(_issue_fields(issue).get(f"customfield_{field_id}"))


def _is_labels_event(event: FieldEvent) -> bool:
    return event.field_name.casefold() == "labels" or event.field_id.casefold() == "labels"


def _is_issue_type_event(event: FieldEvent) -> bool:
    return event.field_name.casefold() == "issuetype" or event.field_id.casefold() == "issuetype"


def _is_selected_custom_field_event(event: FieldEvent, field_id: str | None) -> bool:
    if field_id is None:
        return False
    expected = f"customfield_{field_id}".casefold()
    return event.field_id.casefold() == expected or event.field_name.casefold() == expected


def selector_snapshot_at(
    issue: dict[str, Any], histories: list[FieldEvent], timestamp: datetime, field_id: str | None
) -> SelectorSnapshot:
    labels = set(_current_labels(issue))
    field_value = _current_field_value(issue, field_id)
    issue_type = _current_issue_type(issue)
    for event in reversed(histories):
        if event.timestamp <= timestamp:
            continue
        if _is_labels_event(event):
            labels = set(_split_label_value(event.from_value, event.from_string))
        elif _is_selected_custom_field_event(event, field_id):
            field_value = normalize_value(event.from_value, event.from_string)
        elif _is_issue_type_event(event):
            issue_type = normalize_value(event.from_value, event.from_string)
    return SelectorSnapshot(frozenset(labels), field_value, issue_type)


def _status_events(histories: list[FieldEvent]) -> list[StatusEvent]:
    events = [
        StatusEvent(
            timestamp=event.timestamp,
            from_status=normalize_value(event.from_value, event.from_string),
            to_status=normalize_value(event.to_value, event.to_string),
            history_id=event.history_id,
        )
        for event in histories
        if event.field_name.casefold() == "status" or event.field_id.casefold() == "status"
    ]
    events.sort(key=lambda event: (event.timestamp, _history_sort_key(event.history_id)))
    return events


def _status_key(value: str) -> str:
    return value.strip().casefold()


def reconstruct_cycles(histories: list[FieldEvent], start_statuses: frozenset[str], end_statuses: frozenset[str], year: int) -> list[CycleResult]:
    cycles: list[CycleResult] = []
    open_start: datetime | None = None
    completed_once = False
    current_completed = False
    reopened_pending = False
    for event in _status_events(histories):
        to_status = _status_key(event.to_status)
        if to_status in start_statuses:
            if open_start is None:
                open_start = event.timestamp
                reopened_pending = completed_once
            current_completed = False
            continue
        if to_status not in end_statuses:
            continue
        if current_completed and open_start is None:
            continue
        if open_start is None:
            if event.timestamp.year == year:
                cycles.append(
                    CycleResult(
                        completion_timestamp=event.timestamp,
                        started_at=None,
                        business_seconds=0,
                        missing_start=True,
                        reopened=False,
                    )
                )
            completed_once = True
            current_completed = True
            continue
        seconds = business_time_spent_in_seconds(open_start, event.timestamp)
        if event.timestamp.year == year:
            cycles.append(
                CycleResult(
                    completion_timestamp=event.timestamp,
                    started_at=open_start,
                    business_seconds=seconds,
                    missing_start=False,
                    reopened=reopened_pending,
                )
            )
        open_start = None
        completed_once = True
        current_completed = True
        reopened_pending = False
    return cycles


def _selector_matches(snapshot: SelectorSnapshot, config: ReportConfig) -> bool:
    if snapshot.issue_type.strip().casefold() not in config.issue_types:
        return False
    if config.label and config.label.casefold() not in {label.casefold() for label in snapshot.labels}:
        return False
    if config.field_value and snapshot.field_value.strip() != config.field_value:
        return False
    return True


def select_ticket_cycles(issue: dict[str, Any], histories: list[FieldEvent], config: ReportConfig) -> TicketResult | None:
    matching: list[tuple[CycleResult, SelectorSnapshot]] = []
    for cycle in reconstruct_cycles(histories, config.start_statuses, config.end_statuses, config.year):
        snapshot = selector_snapshot_at(issue, histories, cycle.completion_timestamp, config.field_id)
        if _selector_matches(snapshot, config):
            matching.append((cycle, snapshot))
    if not matching:
        return None

    latest_cycle, latest_snapshot = max(matching, key=lambda item: item[0].completion_timestamp)
    cycles = [cycle for cycle, _ in matching]
    evidence = []
    for cycle, snapshot in matching:
        started = cycle.started_at.isoformat() if cycle.started_at else "(missing)"
        evidence.append(
            json.dumps(
                {
                    "completed": cycle.completion_timestamp.isoformat(),
                    "started": started,
                    "issue_type": snapshot.issue_type,
                    "labels": sorted(snapshot.labels),
                    "field_value": snapshot.field_value,
                    "missing_start": cycle.missing_start,
                    "reopened": cycle.reopened,
                    "business_days": round(cycle.business_seconds / (SECONDS_TO_HOURS * HOURS_TO_DAYS), 4),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    return TicketResult(
        issue_key=str(issue.get("key") or ""),
        issue_id=str(issue.get("id") or ""),
        latest_completion=latest_cycle.completion_timestamp,
        latest_issue_type=latest_snapshot.issue_type,
        matched_label=config.label if config.label else "",
        matched_field_value=latest_snapshot.field_value if config.field_value else "",
        completed_cycles=len(cycles),
        reopened_cycles=sum(cycle.reopened for cycle in cycles),
        measured_cycles=sum(not cycle.missing_start for cycle in cycles),
        missing_start_cycles=sum(cycle.missing_start for cycle in cycles),
        total_business_seconds=sum(cycle.business_seconds for cycle in cycles),
        cycle_evidence=tuple(evidence),
    )


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile
    lower_index = int(rank)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    weight = rank - lower_index
    return ordered[lower_index] + ((ordered[upper_index] - ordered[lower_index]) * weight)


def aggregate_monthly(results: list[TicketResult], year: int) -> list[SummaryRow]:
    rows: list[SummaryRow] = []
    for month in range(1, 13):
        month_key = f"{year}-{month:02d}"
        tickets = [result for result in results if result.latest_completion.strftime("%Y-%m") == month_key]
        ticket_days = [result.total_business_days for result in tickets]
        rows.append(
            SummaryRow(
                month=month_key,
                completed_tickets=len(tickets),
                completed_cycles=sum(ticket.completed_cycles for ticket in tickets),
                reopened_cycles=sum(ticket.reopened_cycles for ticket in tickets),
                measured_cycles=sum(ticket.measured_cycles for ticket in tickets),
                missing_start_cycles=sum(ticket.missing_start_cycles for ticket in tickets),
                tickets_with_missing_start=sum(ticket.missing_start_cycles > 0 for ticket in tickets),
                total_business_days=sum(ticket_days),
                median_business_days=statistics.median(ticket_days) if ticket_days else 0.0,
                p85_business_days=_percentile(ticket_days, 0.85),
            )
        )
    return rows


def _spreadsheet_safe_cell(value: str) -> str:
    meaningful = value.lstrip()
    if meaningful.startswith(CSV_FORMULA_PREFIXES):
        return "'" + value
    return value


def summary_to_row(row: SummaryRow) -> dict[str, str]:
    return {
        "Month": row.month,
        "Completed Tickets": str(row.completed_tickets),
        "Completed Cycles": str(row.completed_cycles),
        "Reopened Cycles": str(row.reopened_cycles),
        "Measured Cycles": str(row.measured_cycles),
        "Cycles Missing Start": str(row.missing_start_cycles),
        "Tickets With Missing Start": str(row.tickets_with_missing_start),
        "Total Business Cycle Days": f"{row.total_business_days:.4f}",
        "Median Business Cycle Days per Ticket": f"{row.median_business_days:.4f}",
        "P85 Business Cycle Days per Ticket": f"{row.p85_business_days:.4f}",
        "Data Complete": "true" if row.data_complete else "false",
    }


def detail_to_row(result: TicketResult) -> dict[str, str]:
    return {
        "Issue Key": result.issue_key,
        "Issue ID": result.issue_id,
        "Issue Type at Latest Completion": result.latest_issue_type,
        "Latest Matching Completion": result.latest_completion.isoformat(),
        "Completion Month": result.latest_completion.strftime("%Y-%m"),
        "Matched Label": result.matched_label,
        "Matched Field Value": result.matched_field_value,
        "Completed Cycles": str(result.completed_cycles),
        "Reopened Cycles": str(result.reopened_cycles),
        "Measured Cycles": str(result.measured_cycles),
        "Cycles Missing Start": str(result.missing_start_cycles),
        "Total Business Cycle Days": f"{result.total_business_days:.4f}",
        "Cycle Evidence": "\n".join(result.cycle_evidence),
    }


def _write_dict_csv(path: Path, columns: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _spreadsheet_safe_cell(row[column]) for column in columns})


def write_outputs(summary_rows: list[SummaryRow], detail_rows: list[TicketResult], output_dir: Path, year: int) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / f"filtered_delivery_time_summary_{year}.csv"
    detail_path = output_dir / f"filtered_delivery_time_details_{year}.csv"
    _write_dict_csv(summary_path, SUMMARY_COLUMNS, [summary_to_row(row) for row in summary_rows])
    _write_dict_csv(detail_path, DETAIL_COLUMNS, [detail_to_row(row) for row in detail_rows])
    return summary_path, detail_path


def _require_complete_search(result: JiraSearchResult) -> None:
    if not result.complete:
        details = " ".join(result.limitations)
        raise ReportError(f"Candidate search was incomplete. {details}")


def _require_complete_changelog(result: ChangelogFetchResult) -> None:
    if not result.complete:
        details = " ".join(result.limitations)
        raise ReportError(f"Changelog retrieval was incomplete. {details}")


def run_report(config: ReportConfig) -> tuple[list[SummaryRow], list[TicketResult], tuple[Path, Path] | None]:
    jql = build_completion_candidate_jql(config.year, config.issue_types, config.end_statuses, config.projects)
    print("Jira JQL:")
    print(jql)
    search_result = search_jira_issues_raw(jql, candidate_fields(config.field_id))
    _require_complete_search(search_result)
    issues_by_key: dict[str, dict[str, Any]] = {}
    for issue in search_result.issues:
        key = str(issue.get("key") or "")
        if key and key not in issues_by_key:
            issues_by_key[key] = issue
    candidate_issues = list(issues_by_key.values())
    id_to_key = {
        str(issue.get("id")): str(issue.get("key"))
        for issue in candidate_issues
        if issue.get("id") is not None and issue.get("key") is not None
    }
    issue_ids = list(id_to_key.keys())
    changelog_result = fetch_complete_changelogs(issue_ids, id_to_key)
    _require_complete_changelog(changelog_result)

    detail_rows: list[TicketResult] = []
    for issue in candidate_issues:
        key = str(issue.get("key") or "")
        histories = normalize_changelog(changelog_result.records_by_issue.get(key, []))
        result = select_ticket_cycles(issue, histories, config)
        if result is not None:
            detail_rows.append(result)
    detail_rows.sort(key=lambda row: (row.latest_completion, row.issue_key))
    summary_rows = aggregate_monthly(detail_rows, config.year)
    paths = write_outputs(summary_rows, detail_rows, config.output_dir, config.year) if config.write_csv else None
    return summary_rows, detail_rows, paths


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        config = build_config(args)
        summary_rows, detail_rows, paths = run_report(config)
    except (ReportError, OSError, ValueError, argparse.ArgumentTypeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    print(f"Filtered delivery time report complete for {config.year}: {len(detail_rows)} ticket(s) selected.")
    if paths is not None:
        print(f"Summary CSV: {paths[0]}")
        print(f"Detail CSV: {paths[1]}")
    elif summary_rows:
        print("CSV output not requested; use -csv to write summary and detail files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
