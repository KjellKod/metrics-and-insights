#!/usr/bin/env python3
"""Audit Jira epic membership changes from complete issue changelogs."""

# pylint: disable=import-error

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
import textwrap
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jira_utils import (
    ChangelogFetchResult,
    JiraFieldResult,
    JiraSearchResult,
    fetch_complete_changelogs,
    get_jira_field_metadata,
    search_jira_issues_raw,
)


CANDIDATE_CUSHION_DAYS = 2
DEFAULT_INPUT_TIMEZONE = "America/Denver"
KNOWN_RELATIONSHIP_NAMES = {"parent", "epiclink", "issueparentassociation"}
EMPTY_RELATIONSHIP_VALUES = {"", "none", "null", "no epic", "no parent"}
JIRA_KEY_AT_START = re.compile(r"^\s*\[?([A-Za-z][A-Za-z0-9_]*-\d+)\b")
CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

EVENT_COLUMNS = (
    "Epic key",
    "Issue key",
    "Issue summary",
    "Issue type",
    "Current status",
    "Event type",
    "Event timestamp",
    "Actor display name",
    "Actor account ID",
    "Previous parent/epic",
    "New parent/epic",
    "Current parent/epic",
    "Later re-added",
    "Changelog field name",
    "Changelog/history ID",
    "Raw changelog evidence",
)


class AuditError(RuntimeError):
    """An actionable fatal audit error."""


@dataclass(frozen=True)
class EpicRef:
    key: str
    issue_id: str


@dataclass(frozen=True)
class RelationshipFields:
    field_ids: frozenset[str]
    field_names: frozenset[str]
    display_names_by_id: dict[str, str]

    def recognizes(self, field_name: str, field_id: str) -> bool:
        return normalize_field_name(field_name) in self.field_names or field_id.casefold() in self.field_ids


@dataclass(frozen=True)
class IssueSnapshot:  # pylint: disable=too-many-instance-attributes
    key: str
    issue_id: str
    summary: str
    issue_type: str
    status: str
    updated: str
    current_parent: str | None
    current_parent_state: str


@dataclass(frozen=True)
class ChangelogEvidence:  # pylint: disable=too-many-instance-attributes
    issue_key: str
    history_id: str
    timestamp: datetime
    actor_display_name: str
    actor_account_id: str
    field_name: str
    field_id: str
    from_value: Any
    from_string: Any
    to_value: Any
    to_string: Any

    @property
    def raw_evidence(self) -> str:
        raw = {
            "field": self.field_name,
            "fieldId": self.field_id,
            "from": self.from_value,
            "fromString": self.from_string,
            "to": self.to_value,
            "toString": self.to_string,
        }
        return json.dumps(raw, sort_keys=True, separators=(",", ":"), default=str)

    @property
    def identity(self) -> tuple[str, ...]:
        return (
            self.issue_key,
            self.history_id,
            self.field_id.casefold() or normalize_field_name(self.field_name),
            json.dumps(
                [self.from_value, self.from_string, self.to_value, self.to_string],
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ),
        )


@dataclass
class MembershipEvent:
    epic_key: str
    issue: IssueSnapshot
    event_type: str
    evidence: ChangelogEvidence
    previous_parent: str
    new_parent: str
    later_re_added: bool = False


@dataclass(frozen=True)
class SummaryCounts:  # pylint: disable=too-many-instance-attributes
    unique_issues: int
    additions: int
    removals: int
    moves_in: int
    moves_out: int
    unique_outbound_issues: int
    later_re_added: int
    currently_other_epic: int
    currently_no_epic: int


@dataclass
class AuditDiagnostics:  # pylint: disable=too-many-instance-attributes
    selector: str
    resolved_epic_keys: list[str]
    since: datetime
    until: datetime
    candidate_jql: str
    candidate_count: int
    changelog_method: str
    every_page_complete: bool
    audit_complete: bool
    input_timezone: str = DEFAULT_INPUT_TIMEZONE
    limitations: list[str] = field(default_factory=list)
    label_selection: bool = False


@dataclass(frozen=True)
class AuditResult:
    events: list[MembershipEvent]
    summaries: dict[str, SummaryCounts]
    overall_summary: SummaryCounts
    diagnostics: AuditDiagnostics


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reconstruct Jira epic membership changes from issue-level changelog evidence."
    )
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--epic", help="Audit one Epic key")
    selector.add_argument("--label", help="Audit all accessible Epics currently carrying this label")
    parser.add_argument(
        "--since",
        required=True,
        help="Inclusive ISO-8601 start; YYYY-MM-DD uses start-of-day in --timezone",
    )
    parser.add_argument(
        "--until",
        help="Inclusive ISO-8601 end; YYYY-MM-DD uses end-of-day in --timezone; defaults to now",
    )
    parser.add_argument(
        "--timezone",
        default=DEFAULT_INPUT_TIMEZONE,
        help=f"IANA timezone for date-only boundaries (default: {DEFAULT_INPUT_TIMEZONE})",
    )
    parser.add_argument("--csv", dest="csv_path", type=Path, help="Export the displayed event rows to CSV")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print sanitized retrieval diagnostics")
    args = parser.parse_args(argv)
    args.since_input = args.since
    args.until_input = args.until
    try:
        input_timezone = ZoneInfo(args.timezone)
    except ZoneInfoNotFoundError:
        parser.error(f"unknown IANA timezone: {args.timezone}")
    try:
        args.since = parse_audit_boundary(args.since, input_timezone, end_of_day=False)
        if args.until is not None:
            args.until = parse_audit_boundary(args.until, input_timezone, end_of_day=True)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    if args.until is not None and args.until < args.since:
        parser.error("--until must be the same as or later than --since")
    return args


def parse_aware_timestamp(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid ISO-8601 timestamp: {value}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include an explicit UTC offset or Z")
    return parsed


def parse_audit_boundary(value: str, input_timezone: ZoneInfo, *, end_of_day: bool) -> datetime:
    """Resolve a CLI boundary while keeping naive clock timestamps invalid."""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            parsed_date = date.fromisoformat(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"invalid ISO-8601 date: {value}") from exc
        boundary_time = time.max if end_of_day else time.min
        return datetime.combine(parsed_date, boundary_time, tzinfo=input_timezone)
    return parse_aware_timestamp(value)


def print_resolved_interval(args: argparse.Namespace, until: datetime) -> None:
    """Confirm the exact inclusive interval before any Jira request."""
    until_input = args.until_input if args.until_input is not None else "(now)"
    print("Resolved audit interval:")
    print(f"  --since {args.since_input} -> {args.since.isoformat()}")
    print(f"  --until {until_input} -> {until.isoformat()}")
    print(f"  Date-only timezone: {args.timezone}")
    print("  Boundaries: inclusive")


def parse_jira_timestamp(value: Any) -> datetime:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value) / 1000 if abs(float(value)) >= 100_000_000_000 else float(value)
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    if not isinstance(value, str):
        raise ValueError("unsupported Jira timestamp")
    normalized = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Jira timestamp is not timezone-aware")
    return parsed


def _history_id_sort_key(history_id: str) -> tuple[int, int | str]:
    """Sort Jira's numeric history IDs numerically with a stable text fallback."""
    stripped = history_id.strip()
    if stripped.isdecimal():
        return (0, int(stripped))
    return (1, stripped.casefold())


def _quote_jql(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_selector_jql(epic: str | None = None, label: str | None = None) -> str:
    if epic:
        return f"key = {_quote_jql(epic.strip())} AND issuetype = Epic"
    if label:
        return f"issuetype = Epic AND labels = {_quote_jql(label)} ORDER BY key ASC"
    raise ValueError("An epic key or label is required")


def build_candidate_jql(since: datetime) -> str:
    boundary = (since.astimezone(timezone.utc) - timedelta(days=CANDIDATE_CUSHION_DAYS)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return f'updated >= "{boundary:%Y-%m-%d %H:%M}" ORDER BY updated ASC'


def normalize_field_name(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def discover_relationship_fields(metadata: list[dict[str, Any]]) -> RelationshipFields:
    names = set(KNOWN_RELATIONSHIP_NAMES)
    field_ids = {"parent", "issueparentassociation"}
    display_names_by_id = {"parent": "Parent", "issueparentassociation": "IssueParentAssociation"}
    for item in metadata:
        name = item.get("name")
        field_id = item.get("id") or item.get("key")
        if not isinstance(name, str) or not isinstance(field_id, str):
            continue
        normalized_name = normalize_field_name(name)
        if normalized_name in KNOWN_RELATIONSHIP_NAMES:
            names.add(normalized_name)
            field_ids.add(field_id.casefold())
            display_names_by_id[field_id.casefold()] = name
    return RelationshipFields(frozenset(field_ids), frozenset(names), display_names_by_id)


def _epic_type(raw_issue: dict[str, Any]) -> bool:
    fields = raw_issue.get("fields", {})
    issue_type = fields.get("issuetype", {}) if isinstance(fields, dict) else {}
    name = issue_type.get("name", "") if isinstance(issue_type, dict) else ""
    return isinstance(name, str) and name.casefold() == "epic"


def resolve_epics(epic: str | None, label: str | None) -> list[EpicRef]:
    jql = build_selector_jql(epic=epic, label=label)
    result = search_jira_issues_raw(jql, ["issuetype"])
    if not result.complete:
        details = " ".join(result.limitations)
        raise AuditError(f"Epic selector query was incomplete. {details}")
    refs = [
        EpicRef(str(issue["key"]), str(issue["id"]))
        for issue in result.issues
        if "key" in issue and "id" in issue and _epic_type(issue)
    ]
    if epic:
        refs = [ref for ref in refs if ref.key.casefold() == epic.strip().casefold()]
        if not refs:
            raise AuditError(f"{epic} was not found as an accessible Epic. Check the key and permissions.")
        return refs[:1]
    return sorted(refs, key=lambda ref: ref.key)


def _relationship_display_value(raw_value: Any, string_value: Any = None) -> str:
    for value in (string_value, raw_value):
        if isinstance(value, dict):
            for key in ("key", "id"):
                nested = value.get(key)
                if nested not in (None, ""):
                    return str(nested)
        if value not in (None, ""):
            return str(value)
    return "(none)"


def _value_is_empty(raw_value: Any, string_value: Any) -> bool:
    present = [value for value in (raw_value, string_value) if value is not None]
    if not present:
        return True
    return all(str(value).strip().casefold() in EMPTY_RELATIONSHIP_VALUES for value in present)


def _selected_epic_for_value(raw_value: Any, string_value: Any, epics: list[EpicRef]) -> str | None:
    aliases = {ref.issue_id.casefold(): ref.key for ref in epics}
    aliases.update({ref.key.casefold(): ref.key for ref in epics})
    if isinstance(raw_value, dict):
        candidates = [raw_value.get("id"), raw_value.get("key")]
    else:
        candidates = [raw_value]
    meaningful_candidates = [
        str(candidate).strip().casefold()
        for candidate in candidates
        if candidate is not None and str(candidate).strip().casefold() not in EMPTY_RELATIONSHIP_VALUES
    ]
    for candidate in meaningful_candidates:
        if candidate in aliases:
            return aliases[candidate]
    if meaningful_candidates:
        return None
    if isinstance(string_value, str):
        exact = string_value.strip().casefold()
        if exact in aliases:
            return aliases[exact]
        match = JIRA_KEY_AT_START.match(string_value)
        if match and match.group(1).casefold() in aliases:
            return aliases[match.group(1).casefold()]
    return None


def _current_relationship_value(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, dict):
        for key in ("key", "id", "value"):
            nested = value.get(key)
            if nested not in (None, ""):
                return str(nested)
        return None
    return str(value)


def build_issue_snapshots(  # pylint: disable=too-many-locals
    raw_issues: list[dict[str, Any]], relationship_fields: RelationshipFields
) -> tuple[dict[str, IssueSnapshot], list[str]]:
    snapshots: dict[str, IssueSnapshot] = {}
    limitations: list[str] = []
    for raw_issue in raw_issues:
        raw_key = raw_issue.get("key")
        if not isinstance(raw_key, str) or not raw_key.strip():
            limitations.append("A candidate issue was omitted because Jira did not return its key.")
            continue
        key = raw_key
        fields = raw_issue.get("fields")
        fields_available = isinstance(fields, dict)
        if not isinstance(fields, dict):
            limitations.append(f"Current relationship for {key} is unknown because issue fields were unavailable.")
            fields = {}
        values: list[str] = []
        recognized_present = False
        for field_id, value in fields.items():
            if not isinstance(field_id, str):
                continue
            if (
                field_id.casefold() in relationship_fields.field_ids
                or normalize_field_name(field_id) in KNOWN_RELATIONSHIP_NAMES
            ):
                recognized_present = True
                current = _current_relationship_value(value)
                if current:
                    values.append(current)
        unique_values = {value.casefold(): value for value in values}
        if len(unique_values) > 1:
            state = "unknown"
            current_parent = None
            limitations.append(f"Current relationship for {key} is unknown because Jira relationship fields conflict.")
        elif len(unique_values) == 1:
            state = "known"
            current_parent = next(iter(unique_values.values()))
        elif recognized_present:
            state = "empty"
            current_parent = None
        elif not fields_available:
            state = "unknown"
            current_parent = None
        else:
            # Jira omits requested fields whose values are null from enhanced
            # search responses. No returned relationship field therefore means
            # the issue currently has no parent/epic, provided the issue fields
            # object itself was available.
            state = "empty"
            current_parent = None

        issue_type = fields.get("issuetype", {})
        status = fields.get("status", {})
        snapshots[key] = IssueSnapshot(
            key=key,
            issue_id=str(raw_issue.get("id", "")),
            summary=str(fields.get("summary") or ""),
            issue_type=str(issue_type.get("name") or "") if isinstance(issue_type, dict) else "",
            status=str(status.get("name") or "") if isinstance(status, dict) else "",
            updated=str(fields.get("updated") or ""),
            current_parent=current_parent,
            current_parent_state=state,
        )
    return snapshots, limitations


def normalize_changelog_records(
    issue_key: str,
    histories: list[dict[str, Any]],
    relationship_fields: RelationshipFields,
) -> tuple[list[ChangelogEvidence], list[str]]:
    evidence: list[ChangelogEvidence] = []
    limitations: list[str] = []
    seen: set[tuple[str, ...]] = set()
    for history in histories:
        history_id = str(history.get("id", ""))
        try:
            timestamp = parse_jira_timestamp(history.get("created"))
        except (ValueError, OverflowError, OSError):
            limitations.append(
                f"Changelog history {history_id or '(unknown)'} for {issue_key} had an invalid timestamp."
            )
            continue
        author = history.get("author") if isinstance(history.get("author"), dict) else {}
        items = history.get("items", [])
        if not isinstance(items, list):
            limitations.append(f"Changelog history {history_id or '(unknown)'} for {issue_key} had invalid items.")
            continue
        for item in items:
            if not isinstance(item, dict):
                limitations.append(
                    f"Changelog history {history_id or '(unknown)'} for {issue_key} had an invalid item."
                )
                continue
            field_name = str(item.get("field") or "")
            field_id = str(item.get("fieldId") or "")
            if not relationship_fields.recognizes(field_name, field_id):
                continue
            record = ChangelogEvidence(
                issue_key=issue_key,
                history_id=history_id,
                timestamp=timestamp,
                actor_display_name=str(author.get("displayName") or ""),
                actor_account_id=str(author.get("accountId") or ""),
                field_name=field_name,
                field_id=field_id,
                from_value=item.get("from"),
                from_string=item.get("fromString"),
                to_value=item.get("to"),
                to_string=item.get("toString"),
            )
            if record.identity not in seen:
                evidence.append(record)
                seen.add(record.identity)
    evidence.sort(
        key=lambda record: (
            record.timestamp,
            _history_id_sort_key(record.history_id),
            record.field_id,
            record.field_name,
        )
    )
    return evidence, limitations


def classify_membership_events(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    snapshots: dict[str, IssueSnapshot],
    histories_by_issue: dict[str, list[dict[str, Any]]],
    epics: list[EpicRef],
    relationship_fields: RelationshipFields,
    since: datetime,
    until: datetime,
) -> tuple[list[MembershipEvent], list[str]]:
    events: list[MembershipEvent] = []
    limitations: list[str] = []
    exited: set[tuple[str, str]] = set()

    for issue_key, snapshot in snapshots.items():
        evidence, issue_limitations = normalize_changelog_records(
            issue_key, histories_by_issue.get(issue_key, []), relationship_fields
        )
        limitations.extend(issue_limitations)
        for record in evidence:
            if record.timestamp > until:
                continue
            previous_epic = _selected_epic_for_value(record.from_value, record.from_string, epics)
            new_epic = _selected_epic_for_value(record.to_value, record.to_string, epics)
            previous_empty = _value_is_empty(record.from_value, record.from_string)
            new_empty = _value_is_empty(record.to_value, record.to_string)
            previous_display = _relationship_display_value(record.from_value, record.from_string)
            new_display = _relationship_display_value(record.to_value, record.to_string)

            perspectives: list[tuple[str, str]] = []
            if previous_epic and previous_epic != new_epic:
                perspectives.append((previous_epic, "removed" if new_empty else "moved_out"))
                exited.add((issue_key, previous_epic))
            if new_epic and new_epic != previous_epic:
                state_key = (issue_key, new_epic)
                if state_key in exited:
                    event_type = "re_added"
                else:
                    event_type = "added" if previous_empty else "moved_in"
                perspectives.append((new_epic, event_type))

            if record.timestamp < since:
                continue
            for epic_key, event_type in perspectives:
                events.append(
                    MembershipEvent(
                        epic_key=epic_key,
                        issue=snapshot,
                        event_type=event_type,
                        evidence=record,
                        previous_parent=previous_display,
                        new_parent=new_display,
                    )
                )

    events.sort(
        key=lambda event: (
            event.evidence.timestamp,
            event.issue.key,
            _history_id_sort_key(event.evidence.history_id),
            event.epic_key,
            event.event_type,
        )
    )
    for index, event in enumerate(events):
        if event.event_type not in ("removed", "moved_out"):
            continue
        event.later_re_added = any(
            later.issue.key == event.issue.key and later.epic_key == event.epic_key and later.event_type == "re_added"
            for later in events[index + 1 :]
        )
    return events, limitations


def _current_parent_display(issue: IssueSnapshot) -> str:
    if issue.current_parent_state == "unknown":
        return "Unknown"
    return issue.current_parent or "(none)"


def event_to_row(event: MembershipEvent) -> dict[str, str]:
    return {
        "Epic key": event.epic_key,
        "Issue key": event.issue.key,
        "Issue summary": event.issue.summary,
        "Issue type": event.issue.issue_type,
        "Current status": event.issue.status,
        "Event type": event.event_type,
        "Event timestamp": event.evidence.timestamp.isoformat(),
        "Actor display name": event.evidence.actor_display_name,
        "Actor account ID": event.evidence.actor_account_id,
        "Previous parent/epic": event.previous_parent,
        "New parent/epic": event.new_parent,
        "Current parent/epic": _current_parent_display(event.issue),
        "Later re-added": "yes" if event.later_re_added else "no",
        "Changelog field name": event.evidence.field_name,
        "Changelog/history ID": event.evidence.history_id,
        "Raw changelog evidence": event.evidence.raw_evidence,
    }


def _wrapped_report_field(label: str, value: str, width: int) -> list[str]:
    prefix = f"  {label}: "
    continuation = " " * len(prefix)
    available = max(1, width - len(prefix))
    wrapped = textwrap.wrap(
        value or "(not available)",
        width=available,
        break_long_words=True,
        break_on_hyphens=False,
    ) or [""]
    return [prefix + wrapped[0], *(continuation + line for line in wrapped[1:])]


def build_table_lines(events: list[MembershipEvent], width: int = 100) -> list[str]:
    rows = [event_to_row(event) for event in events]
    if not rows:
        return ["No epic membership changes were found in the requested interval."]
    width = max(40, width)
    lines: list[str] = []
    for index, row in enumerate(rows, start=1):
        if lines:
            lines.append("")
        heading = f"Event {index} of {len(rows)}"
        lines.extend((heading, "-" * len(heading)))
        for column in EVENT_COLUMNS:
            lines.extend(_wrapped_report_field(column, row[column], width))
    return lines


def unique_messages(messages: list[str]) -> list[str]:
    """Deduplicate diagnostic text while preserving its first-seen order."""
    return list(dict.fromkeys(messages))


def write_csv(events: list[MembershipEvent], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=EVENT_COLUMNS)
        writer.writeheader()
        for event in events:
            row = event_to_row(event)
            writer.writerow({column: _spreadsheet_safe_cell(value) for column, value in row.items()})


def _spreadsheet_safe_cell(value: str) -> str:
    """Prevent untrusted Jira text from being evaluated as a spreadsheet formula."""
    meaningful = value.lstrip()
    if meaningful.startswith(CSV_FORMULA_PREFIXES):
        return "'" + value
    return value


def _summary_for_events(
    events: list[MembershipEvent], epic: EpicRef | None = None, epic_refs: list[EpicRef] | None = None
) -> SummaryCounts:
    issue_keys = {event.issue.key for event in events}
    outbound = [event for event in events if event.event_type in ("removed", "moved_out")]
    outbound_issues = {event.issue.key: event.issue for event in outbound}
    later_readded = {event.issue.key for event in outbound if event.later_re_added}
    current_aliases = {epic.key.casefold(), epic.issue_id.casefold()} if epic else set()
    refs_by_key = {ref.key: ref for ref in epic_refs or []}

    def currently_in_other_epic(issue_key: str, issue: IssueSnapshot) -> bool:
        if issue.current_parent_state != "known" or not issue.current_parent:
            return False
        current = issue.current_parent.casefold()
        if current_aliases:
            return current not in current_aliases
        for event in outbound:
            if event.issue.key != issue_key:
                continue
            event_epic = refs_by_key.get(event.epic_key)
            aliases = {event.epic_key.casefold()}
            if event_epic:
                aliases.add(event_epic.issue_id.casefold())
            if current not in aliases:
                return True
        return False

    return SummaryCounts(
        unique_issues=len(issue_keys),
        additions=sum(event.event_type == "added" for event in events),
        removals=sum(event.event_type == "removed" for event in events),
        moves_in=sum(event.event_type == "moved_in" for event in events),
        moves_out=sum(event.event_type == "moved_out" for event in events),
        unique_outbound_issues=len(outbound_issues),
        later_re_added=len(later_readded),
        currently_other_epic=sum(
            currently_in_other_epic(issue_key, issue) for issue_key, issue in outbound_issues.items()
        ),
        currently_no_epic=sum(issue.current_parent_state == "empty" for issue in outbound_issues.values()),
    )


def summarize_events(
    events: list[MembershipEvent], epics: list[EpicRef]
) -> tuple[dict[str, SummaryCounts], SummaryCounts]:
    summaries = {
        epic.key: _summary_for_events([event for event in events if event.epic_key == epic.key], epic) for epic in epics
    }
    overall = _summary_for_events(events, epic_refs=epics)
    return summaries, overall


def _print_summary(title: str, summary: SummaryCounts) -> None:
    print(f"\n{title}")
    print(f"  Total unique issues with membership changes: {summary.unique_issues}")
    print(f"  Total additions: {summary.additions}")
    print(f"  Total removals to no epic: {summary.removals}")
    print(f"  Total moves into the epic: {summary.moves_in}")
    print(f"  Total moves out to another epic: {summary.moves_out}")
    print(f"  Total unique issues removed or moved out: {summary.unique_outbound_issues}")
    print(f"  Total later re-added: {summary.later_re_added}")
    print(f"  Total currently assigned to another epic: {summary.currently_other_epic}")
    print(f"  Total currently without an epic: {summary.currently_no_epic}")


def render_result(result: AuditResult) -> None:
    print("\nEpic membership events")
    output_width = min(100, shutil.get_terminal_size(fallback=(100, 24)).columns)
    for line in build_table_lines(result.events, width=output_width):
        print(line)
    for epic_key in result.diagnostics.resolved_epic_keys:
        _print_summary(f"Summary for {epic_key}", result.summaries[epic_key])
    _print_summary("Overall summary", result.overall_summary)

    diagnostics = result.diagnostics
    print("\nAudit method and limitations")
    print(f"  Epic selector used: {diagnostics.selector}")
    print(f"  Resolved epic keys: {', '.join(diagnostics.resolved_epic_keys)}")
    print(f"  Audit interval: [{diagnostics.since.isoformat()}, {diagnostics.until.isoformat()}] (inclusive)")
    print(f"  Date-only input timezone: {diagnostics.input_timezone}")
    print(f"  Candidate JQL: {diagnostics.candidate_jql}")
    print(f"  Candidate issue count: {diagnostics.candidate_count}")
    print(f"  Changelog endpoint/method used: {diagnostics.changelog_method}")
    print(f"  Every page completed successfully: {'yes' if diagnostics.every_page_complete else 'no'}")
    print(f"  Audit data complete for accessible scope: {'yes' if diagnostics.audit_complete else 'no'}")
    print("  Project scope: all projects accessible to the authenticated Jira account; no project restriction applied.")
    print("  Permission limitation: inaccessible projects, issues, or secured changelog entries cannot be enumerated.")
    print("  Current fields are execution-time snapshots, including status and current parent/epic.")
    print("  Current relationship values marked Unknown are excluded from both current-destination counters.")
    if diagnostics.label_selection:
        print(
            "  Current-label-selection limitation: only accessible Epics currently carrying the label are discovered; "
            "Epics whose label was removed earlier are not included."
        )
    if diagnostics.limitations:
        print("  Retrieval/data limitations:")
        for limitation in diagnostics.limitations:
            print(f"    - {limitation}")
    else:
        print("  Retrieval/data limitations: none reported by completed API pages.")


def _candidate_fields(relationship_fields: RelationshipFields) -> list[str]:
    fields = {"summary", "issuetype", "status", "parent", "updated"}
    fields.update(field_id for field_id in relationship_fields.field_ids if field_id.startswith("customfield_"))
    return sorted(fields)


def run_audit(args: argparse.Namespace) -> AuditResult | None:  # pylint: disable=too-many-locals
    until = args.until or datetime.now(ZoneInfo(args.timezone))
    if until < args.since:
        raise AuditError("--until must be the same as or later than --since")
    print_resolved_interval(args, until)
    epics = resolve_epics(args.epic, args.label)
    print(f"Resolved epic keys: {', '.join(ref.key for ref in epics) if epics else '(none)'}")
    if args.label and not epics:
        print(
            "No accessible Epics currently carry that label. Check the label and permissions; "
            "historically labeled Epics are not discoverable after the label is removed."
        )
        return None

    field_result: JiraFieldResult = get_jira_field_metadata()
    relationship_fields = discover_relationship_fields(field_result.fields)
    candidate_jql = build_candidate_jql(args.since)
    print(f"Candidate JQL: {candidate_jql}")
    candidate_result: JiraSearchResult = search_jira_issues_raw(candidate_jql, _candidate_fields(relationship_fields))
    snapshots, snapshot_limitations = build_issue_snapshots(candidate_result.issues, relationship_fields)
    id_to_key = {snapshot.issue_id: snapshot.key for snapshot in snapshots.values() if snapshot.issue_id}
    candidate_ids = [snapshot.issue_id or snapshot.key for snapshot in snapshots.values()]
    changelog_result: ChangelogFetchResult = fetch_complete_changelogs(candidate_ids, id_to_key)
    events, evidence_limitations = classify_membership_events(
        snapshots,
        changelog_result.records_by_issue,
        epics,
        relationship_fields,
        args.since,
        until,
    )
    limitations = unique_messages(
        [
            *field_result.limitations,
            *candidate_result.limitations,
            *snapshot_limitations,
            *changelog_result.limitations,
            *evidence_limitations,
        ]
    )
    every_page_complete = field_result.complete and candidate_result.complete and changelog_result.complete
    audit_complete = every_page_complete and not snapshot_limitations and not evidence_limitations
    epic_keys = [ref.key for ref in epics]
    summaries, overall = summarize_events(events, epics)
    diagnostics = AuditDiagnostics(
        selector=f"--epic {args.epic}" if args.epic else f"--label {args.label}",
        resolved_epic_keys=epic_keys,
        since=args.since,
        until=until,
        candidate_jql=candidate_jql,
        candidate_count=len(snapshots),
        changelog_method=changelog_result.method,
        every_page_complete=every_page_complete,
        audit_complete=audit_complete,
        input_timezone=args.timezone,
        limitations=limitations,
        label_selection=bool(args.label),
    )
    if args.verbose:
        print(
            f"Retrieved {candidate_result.page_count} candidate page(s) and "
            f"{changelog_result.page_count} changelog page(s) using {changelog_result.method}."
        )
    return AuditResult(events, summaries, overall, diagnostics)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = run_audit(args)
        if result is None:
            return 0
        render_result(result)
        if args.csv_path:
            write_csv(result.events, args.csv_path)
            print(f"\nCSV written to: {args.csv_path}")
        return 0 if result.diagnostics.audit_complete else 2
    except (AuditError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
