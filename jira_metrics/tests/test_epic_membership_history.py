"""Tests for the changelog-evidence epic membership audit."""

import argparse
import csv
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
# pylint: disable=wrong-import-position,import-error
import epic_membership_history as audit
from jira_utils import ChangelogFetchResult, JiraFieldResult, JiraSearchResult


SINCE = datetime(2024, 1, 1, tzinfo=timezone.utc)
UNTIL = datetime(2024, 1, 31, 23, 59, tzinfo=timezone.utc)
EPIC_A = audit.EpicRef("EPIC-1", "10001")
EPIC_B = audit.EpicRef("EPIC-2", "10002")


def snapshot(key="WORK-1", current_parent="EPIC-1", current_state="known"):
    return audit.IssueSnapshot(
        key=key,
        issue_id=f"id-{key}",
        summary=f"Summary for {key}",
        issue_type="Story",
        status="In Progress",
        updated="2024-02-10T00:00:00+00:00",
        current_parent=current_parent,
        current_parent_state=current_state,
    )


def history(
    history_id,
    created,
    previous,
    new,
    *,
    field_name="Parent",
    field_id="parent",
    previous_id=None,
    new_id=None,
):
    return {
        "id": history_id,
        "created": created,
        "author": {"displayName": "Example Actor", "accountId": "account-1"},
        "items": [
            {
                "field": field_name,
                "fieldId": field_id,
                "from": previous_id,
                "fromString": previous,
                "to": new_id,
                "toString": new,
            }
        ],
    }


def registry(metadata=None):
    return audit.discover_relationship_fields(metadata or [])


def classify(histories, *, issues=None, epics=None, fields=None):
    snapshots = issues or {"WORK-1": snapshot()}
    records = {key: histories if key == "WORK-1" else [] for key in snapshots}
    return audit.classify_membership_events(
        snapshots,
        records,
        epics or [EPIC_A],
        fields or registry(),
        SINCE,
        UNTIL,
    )


class TestCliAndSelection(unittest.TestCase):
    def test_parse_args_requires_exactly_one_epic_selector(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            audit.parse_args(["--since", "2024-01-01T00:00:00Z"])

    def test_parse_args_rejects_epic_and_label_together(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            audit.parse_args(["--epic", "EPIC-1", "--label", "quarter", "--since", "2024-01-01T00:00:00Z"])

    def test_parse_aware_timestamp_rejects_naive_value(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            audit.parse_aware_timestamp("2024-01-01T00:00:00")

    def test_date_only_since_defaults_to_denver_and_observes_dst(self):
        summer = audit.parse_args(["--epic", "EPIC-1", "--since", "2026-07-06"])
        winter = audit.parse_args(["--epic", "EPIC-1", "--since", "2026-01-06"])

        self.assertEqual(summer.timezone, "America/Denver")
        self.assertEqual(summer.since.isoformat(), "2026-07-06T00:00:00-06:00")
        self.assertEqual(winter.since.isoformat(), "2026-01-06T00:00:00-07:00")

    def test_date_only_until_means_end_of_day_in_selected_timezone(self):
        args = audit.parse_args(
            [
                "--epic",
                "EPIC-1",
                "--since",
                "2026-07-06",
                "--until",
                "2026-07-07",
                "--timezone",
                "America/Los_Angeles",
            ]
        )

        self.assertEqual(args.since.isoformat(), "2026-07-06T00:00:00-07:00")
        self.assertEqual(args.until.isoformat(), "2026-07-07T23:59:59.999999-07:00")

    def test_explicit_offset_is_preserved_and_naive_clock_time_is_rejected(self):
        args = audit.parse_args(["--epic", "EPIC-1", "--since", "2026-07-06T00:00:00Z", "--timezone", "America/Denver"])
        self.assertEqual(args.since.isoformat(), "2026-07-06T00:00:00+00:00")

        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            audit.parse_args(["--epic", "EPIC-1", "--since", "2026-07-06T12:00:00"])

    def test_invalid_timezone_is_rejected(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            audit.parse_args(["--epic", "EPIC-1", "--since", "2026-07-06", "--timezone", "Not/A_Timezone"])

    def test_resolved_interval_is_confirmed_before_audit(self):
        args = audit.parse_args(["--epic", "EPIC-1", "--since", "2026-07-06", "--until", "2026-07-07"])
        output = io.StringIO()

        with redirect_stdout(output):
            audit.print_resolved_interval(args, args.until)

        rendered = output.getvalue()
        self.assertIn("Resolved audit interval:", rendered)
        self.assertIn("--since 2026-07-06 -> 2026-07-06T00:00:00-06:00", rendered)
        self.assertIn("--until 2026-07-07 -> 2026-07-07T23:59:59.999999-06:00", rendered)
        self.assertIn("Date-only timezone: America/Denver", rendered)
        self.assertIn("Boundaries: inclusive", rendered)

    def test_interval_rejects_until_before_since(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            audit.parse_args(
                [
                    "--epic",
                    "EPIC-1",
                    "--since",
                    "2024-01-02T00:00:00Z",
                    "--until",
                    "2024-01-01T00:00:00Z",
                ]
            )

    @patch("epic_membership_history.search_jira_issues_raw")
    def test_epic_selector_resolves_only_supplied_epic(self, mock_search):
        mock_search.return_value = JiraSearchResult(
            [
                {"id": "10001", "key": "EPIC-1", "fields": {"issuetype": {"name": "Epic"}}},
                {"id": "10002", "key": "EPIC-2", "fields": {"issuetype": {"name": "Epic"}}},
            ],
            True,
        )

        result = audit.resolve_epics("EPIC-1", None)

        self.assertEqual(result, [EPIC_A])
        self.assertEqual(mock_search.call_args.args[0], 'key = "EPIC-1" AND issuetype = Epic')

    @patch("epic_membership_history.search_jira_issues_raw")
    def test_label_selector_resolves_every_current_matching_epic_and_excludes_non_epics(self, mock_search):
        mock_search.return_value = JiraSearchResult(
            [
                {"id": "10002", "key": "EPIC-2", "fields": {"issuetype": {"name": "Epic"}}},
                {"id": "20001", "key": "WORK-1", "fields": {"issuetype": {"name": "Story"}}},
                {"id": "10001", "key": "EPIC-1", "fields": {"issuetype": {"name": "Epic"}}},
            ],
            True,
        )

        result = audit.resolve_epics(None, "current-label")

        self.assertEqual(result, [EPIC_A, EPIC_B])
        self.assertIn("issuetype = Epic", mock_search.call_args.args[0])
        self.assertIn('labels = "current-label"', mock_search.call_args.args[0])

    @patch("epic_membership_history.resolve_epics", return_value=[])
    def test_label_selector_with_no_epics_exits_cleanly_with_actionable_message(self, _mock_resolve):
        output = io.StringIO()
        with redirect_stdout(output):
            status = audit.main(["--label", "missing", "--since", "2024-01-01T00:00:00Z"])

        self.assertEqual(status, 0)
        self.assertIn("No accessible Epics currently carry that label", output.getvalue())
        self.assertIn("historically labeled", output.getvalue())


class TestCandidateAndRelationshipDiscovery(unittest.TestCase):
    def test_candidate_jql_uses_updated_lower_bound_not_created_or_upper_bound(self):
        jql = audit.build_candidate_jql(datetime(2024, 3, 10, 12, tzinfo=timezone.utc))

        self.assertIn('updated >= "2024-03-08 00:00"', jql)
        self.assertNotIn("created", jql.casefold())
        self.assertEqual(jql.casefold().count("updated"), 2)  # predicate plus ordering only
        self.assertNotIn("<=", jql)

    def test_discovered_legacy_field_id_is_recognized(self):
        fields = registry([{"id": "customfield_12345", "name": "Epic Link"}])

        self.assertTrue(fields.recognizes("Legacy relationship", "customfield_12345"))

    def test_absent_requested_relationship_fields_mean_no_current_epic(self):
        raw_issues = [{"id": "1", "key": "WORK-1", "fields": {"summary": "No parent"}}]

        snapshots, limitations = audit.build_issue_snapshots(raw_issues, registry())

        self.assertEqual(snapshots["WORK-1"].current_parent_state, "empty")
        self.assertIsNone(snapshots["WORK-1"].current_parent)
        self.assertEqual(limitations, [])

    def test_unavailable_or_conflicting_current_relationship_is_unknown(self):
        raw_issues = [
            {"id": "1", "key": "WORK-1"},
            {
                "id": "2",
                "key": "WORK-2",
                "fields": {"parent": {"key": "EPIC-1"}, "issueParentAssociation": "EPIC-2"},
            },
        ]

        snapshots, limitations = audit.build_issue_snapshots(raw_issues, registry())

        self.assertEqual(snapshots["WORK-1"].current_parent_state, "unknown")
        self.assertEqual(snapshots["WORK-2"].current_parent_state, "unknown")
        self.assertEqual(len(limitations), 2)


class TestClassification(unittest.TestCase):
    def test_interval_includes_exact_since_and_until_boundaries(self):
        records = [
            history("h-1", SINCE.isoformat(), None, "EPIC-1"),
            history("h-2", UNTIL.isoformat(), "EPIC-1", None),
        ]

        events, _ = classify(records)

        self.assertEqual([event.event_type for event in events], ["added", "removed"])

    def test_old_issue_removed_after_since_is_reported(self):
        raw_issue = {
            "id": "1",
            "key": "WORK-1",
            "fields": {
                "created": "2010-01-01T00:00:00Z",
                "updated": "2024-02-10T00:00:00Z",
                "parent": None,
            },
        }
        snapshots, _ = audit.build_issue_snapshots([raw_issue], registry())

        events, _ = classify(
            [history("h-1", "2024-01-02T00:00:00Z", "EPIC-1", None)],
            issues=snapshots,
        )

        self.assertEqual([event.event_type for event in events], ["removed"])

    def test_relationship_name_and_discovered_id_variants(self):
        fields = registry([{"id": "customfield_12345", "name": "Epic Link"}])
        variants = [
            ("Parent", "parent"),
            ("epic link", ""),
            ("IssueParentAssociation", "issueparentassociation"),
            ("Legacy relationship", "customfield_12345"),
        ]
        for field_name, field_id in variants:
            with self.subTest(field_name=field_name, field_id=field_id):
                records = [
                    history(
                        f"h-{field_name}",
                        "2024-01-02T00:00:00Z",
                        None,
                        "EPIC-1",
                        field_name=field_name,
                        field_id=field_id,
                    )
                ]
                events, _ = classify(records, fields=fields)
                self.assertEqual([event.event_type for event in events], ["added"])

    def test_add_move_remove_and_move_out_classifications(self):
        cases = [
            (None, "EPIC-1", "added"),
            ("OTHER-1", "EPIC-1", "moved_in"),
            ("EPIC-1", None, "removed"),
            ("EPIC-1", "OTHER-1", "moved_out"),
        ]
        for previous, new, expected in cases:
            with self.subTest(expected=expected):
                events, _ = classify([history("h-1", "2024-01-02T00:00:00Z", previous, new)])
                self.assertEqual([event.event_type for event in events], [expected])

    def test_removal_followed_by_entry_is_re_added_and_marks_outbound(self):
        records = [
            history("h-0", "2023-12-31T00:00:00Z", "EPIC-1", None),
            history("h-1", "2024-01-02T00:00:00Z", None, "EPIC-1"),
            history("h-2", "2024-01-03T00:00:00Z", "EPIC-1", None),
            history("h-3", "2024-01-04T00:00:00Z", None, "EPIC-1"),
        ]

        events, _ = classify(records)

        self.assertEqual([event.event_type for event in events], ["re_added", "removed", "re_added"])
        self.assertTrue(events[1].later_re_added)

    def test_repeated_removals_retained_but_exact_duplicates_removed(self):
        first = history("h-1", "2024-01-02T00:00:00Z", "EPIC-1", None)
        records = [
            first,
            first.copy(),
            history("h-2", "2024-01-03T00:00:00Z", None, "EPIC-1"),
            history("h-3", "2024-01-04T00:00:00Z", "EPIC-1", None),
        ]

        events, _ = classify(records)

        self.assertEqual([event.event_type for event in events].count("removed"), 2)
        self.assertEqual(len(events), 3)

    def test_same_timestamp_histories_sort_numeric_ids_numerically(self):
        timestamp = "2024-01-02T00:00:00Z"
        records = [
            history("10", timestamp, "EPIC-1", None),
            history("2", timestamp, None, "EPIC-1"),
        ]

        events, _ = classify(records)

        self.assertEqual([event.evidence.history_id for event in events], ["2", "10"])
        self.assertEqual([event.event_type for event in events], ["added", "removed"])

    def test_currently_assigned_issue_without_removal_evidence_is_not_reported(self):
        events, _ = classify([])
        self.assertEqual(events, [])

    def test_move_between_selected_epics_emits_both_perspectives(self):
        events, _ = classify(
            [history("h-1", "2024-01-02T00:00:00Z", "EPIC-1", "EPIC-2")],
            epics=[EPIC_A, EPIC_B],
        )

        self.assertEqual(
            {(event.epic_key, event.event_type) for event in events},
            {("EPIC-1", "moved_out"), ("EPIC-2", "moved_in")},
        )
        summaries, overall = audit.summarize_events(events, [EPIC_A, EPIC_B])
        self.assertEqual(summaries["EPIC-1"].moves_out, 1)
        self.assertEqual(summaries["EPIC-2"].moves_in, 1)
        self.assertEqual(overall.unique_issues, 1)

    def test_author_and_raw_changelog_evidence_are_retained(self):
        events, _ = classify(
            [
                history(
                    "h-1",
                    "2024-01-02T00:00:00Z",
                    None,
                    "EPIC-1",
                    new_id="10001",
                )
            ]
        )

        event = events[0]
        self.assertEqual(event.evidence.actor_display_name, "Example Actor")
        self.assertEqual(event.evidence.actor_account_id, "account-1")
        self.assertIn('"to":"10001"', event.evidence.raw_evidence)
        self.assertIn('"toString":"EPIC-1"', event.evidence.raw_evidence)

    def test_display_summary_mention_does_not_match_selected_epic(self):
        events, _ = classify(
            [
                history(
                    "h-1",
                    "2024-01-02T00:00:00Z",
                    "OTHER-9 Summary mentions EPIC-1",
                    None,
                )
            ]
        )

        self.assertEqual(events, [])

    def test_contradictory_raw_id_prevents_display_string_match(self):
        events, _ = classify(
            [
                history(
                    "h-1",
                    "2024-01-02T00:00:00Z",
                    "EPIC-1 Summary text",
                    None,
                    previous_id="99999",
                )
            ]
        )

        self.assertEqual(events, [])


class TestReportingAndOrchestration(unittest.TestCase):
    def _eventful_result(self):
        issues = {
            "WORK-1": snapshot("WORK-1", current_parent="EPIC-1"),
            "WORK-2": snapshot("WORK-2", current_parent="OTHER-1"),
        }
        histories = {
            "WORK-1": [
                history("h-1", "2024-01-02T00:00:00Z", None, "EPIC-1"),
                history("h-2", "2024-01-03T00:00:00Z", "EPIC-1", None),
                history("h-3", "2024-01-04T00:00:00Z", None, "EPIC-1"),
            ],
            "WORK-2": [
                history("h-4", "2024-01-05T00:00:00Z", "OTHER-1", "EPIC-1"),
                history("h-5", "2024-01-06T00:00:00Z", "EPIC-1", "OTHER-1"),
            ],
        }
        events, _ = audit.classify_membership_events(issues, histories, [EPIC_A], registry(), SINCE, UNTIL)
        summaries, overall = audit.summarize_events(events, [EPIC_A])
        diagnostics = audit.AuditDiagnostics(
            selector="--epic EPIC-1",
            resolved_epic_keys=["EPIC-1"],
            since=SINCE,
            until=UNTIL,
            candidate_jql='updated >= "2023-12-30 00:00" ORDER BY updated ASC',
            candidate_count=2,
            changelog_method="bulk",
            every_page_complete=True,
            audit_complete=True,
        )
        return audit.AuditResult(events, summaries, overall, diagnostics)

    def test_event_rows_shared_by_table_and_csv_and_chronological(self):
        result = self._eventful_result()
        rows = [audit.event_to_row(event) for event in result.events]
        self.assertEqual(list(rows[0]), list(audit.EVENT_COLUMNS))
        self.assertEqual([row["Event timestamp"] for row in rows], sorted(row["Event timestamp"] for row in rows))
        table_lines = audit.build_table_lines(result.events, width=80)
        table = "\n".join(table_lines)
        for column in audit.EVENT_COLUMNS:
            self.assertIn(column, table)
        self.assertTrue(all(len(line) <= 80 for line in table_lines))
        self.assertIn("Event 1 of", table)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.csv"
            audit.write_csv(result.events, path)
            with path.open(encoding="utf-8", newline="") as source:
                csv_rows = list(csv.DictReader(source))
        self.assertEqual(csv_rows, rows)

    def test_duplicate_diagnostic_messages_are_retained_once(self):
        message = "Complete per-issue fallback was used."

        self.assertEqual(audit.unique_messages([message, "Different note.", message]), [message, "Different note."])

    def test_csv_prefixes_formula_like_untrusted_jira_text(self):
        result = self._eventful_result()
        unsafe_issue = replace(result.events[0].issue, summary='=HYPERLINK("https://example.invalid")')
        unsafe_event = replace(result.events[0], issue=unsafe_issue)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.csv"
            audit.write_csv([unsafe_event], path)
            with path.open(encoding="utf-8", newline="") as source:
                csv_row = next(csv.DictReader(source))

        self.assertEqual(audit.event_to_row(unsafe_event)["Issue summary"][0], "=")
        self.assertTrue(csv_row["Issue summary"].startswith("'="))

    def test_all_per_epic_and_overall_summary_counts(self):
        result = self._eventful_result()
        expected = audit.SummaryCounts(
            unique_issues=2,
            additions=1,
            removals=1,
            moves_in=1,
            moves_out=1,
            unique_outbound_issues=2,
            later_re_added=1,
            currently_other_epic=1,
            currently_no_epic=0,
        )
        self.assertEqual(result.summaries["EPIC-1"], expected)
        self.assertEqual(result.overall_summary, expected)

    def test_zero_event_report_keeps_summaries_and_method_fields(self):
        empty = audit.SummaryCounts(0, 0, 0, 0, 0, 0, 0, 0, 0)
        diagnostics = audit.AuditDiagnostics(
            selector="--label example",
            resolved_epic_keys=["EPIC-1"],
            since=SINCE,
            until=UNTIL,
            candidate_jql="updated >= boundary",
            candidate_count=0,
            changelog_method="bulk",
            every_page_complete=True,
            audit_complete=True,
            label_selection=True,
        )
        result = audit.AuditResult([], {"EPIC-1": empty}, empty, diagnostics)
        output = io.StringIO()

        with redirect_stdout(output):
            audit.render_result(result)

        rendered = output.getvalue()
        self.assertIn("No epic membership changes", rendered)
        self.assertIn("Total additions: 0", rendered)
        self.assertIn("Epic selector used: --label example", rendered)
        self.assertIn("Resolved epic keys: EPIC-1", rendered)
        self.assertIn("Audit interval:", rendered)
        self.assertIn("Date-only input timezone: America/Denver", rendered)
        self.assertIn("Candidate JQL:", rendered)
        self.assertIn("Candidate issue count: 0", rendered)
        self.assertIn("Changelog endpoint/method used: bulk", rendered)
        self.assertIn("Every page completed successfully: yes", rendered)
        self.assertIn("Audit data complete for accessible scope: yes", rendered)
        self.assertIn("Current-label-selection limitation", rendered)

    @patch("epic_membership_history.fetch_complete_changelogs")
    @patch("epic_membership_history.search_jira_issues_raw")
    @patch("epic_membership_history.get_jira_field_metadata")
    @patch("epic_membership_history.resolve_epics")
    def test_partial_api_failure_is_limitation_and_nonzero_status(
        self, mock_resolve, mock_metadata, mock_search, mock_changelogs
    ):
        mock_resolve.return_value = [EPIC_A]
        mock_metadata.return_value = JiraFieldResult([], True)
        mock_search.return_value = JiraSearchResult([], False, ["candidate page failed"], 1)
        mock_changelogs.return_value = ChangelogFetchResult({}, "bulk", True)
        output = io.StringIO()

        with redirect_stdout(output):
            status = audit.main(["--epic", "EPIC-1", "--since", "2024-01-01T00:00:00Z"])

        self.assertEqual(status, 2)
        self.assertIn("Every page completed successfully: no", output.getvalue())
        self.assertIn("candidate page failed", output.getvalue())

    def test_unknown_current_parent_excluded_from_destination_counters(self):
        issues = {"WORK-1": snapshot(current_parent=None, current_state="unknown")}
        events, _ = classify(
            [history("h-1", "2024-01-02T00:00:00Z", "EPIC-1", None)],
            issues=issues,
        )
        summaries, _ = audit.summarize_events(events, [EPIC_A])

        self.assertEqual(summaries["EPIC-1"].currently_other_epic, 0)
        self.assertEqual(summaries["EPIC-1"].currently_no_epic, 0)

    def test_overall_current_other_deduplicates_any_qualifying_epic_perspective(self):
        issue = snapshot(current_parent="EPIC-2")
        evidence_a, _ = audit.normalize_changelog_records(
            "WORK-1",
            [history("h-1", "2024-01-02T00:00:00Z", "EPIC-1", "EPIC-2")],
            registry(),
        )
        evidence_b, _ = audit.normalize_changelog_records(
            "WORK-1",
            [history("h-2", "2024-01-03T00:00:00Z", "EPIC-2", None)],
            registry(),
        )
        events = [
            audit.MembershipEvent("EPIC-1", issue, "moved_out", evidence_a[0], "EPIC-1", "EPIC-2"),
            audit.MembershipEvent("EPIC-2", issue, "removed", evidence_b[0], "EPIC-2", "(none)"),
        ]

        _, overall = audit.summarize_events(events, [EPIC_A, EPIC_B])

        self.assertEqual(overall.unique_outbound_issues, 1)
        self.assertEqual(overall.currently_other_epic, 1)

    @patch("epic_membership_history.fetch_complete_changelogs")
    @patch("epic_membership_history.search_jira_issues_raw")
    @patch("epic_membership_history.get_jira_field_metadata")
    @patch("epic_membership_history.resolve_epics")
    def test_verbose_output_never_contains_api_token(self, mock_resolve, mock_metadata, mock_search, mock_changelogs):
        mock_resolve.return_value = [EPIC_A]
        mock_metadata.return_value = JiraFieldResult([], True)
        mock_search.return_value = JiraSearchResult([], True, page_count=2)
        mock_changelogs.return_value = ChangelogFetchResult({}, "bulk", True, page_count=3)
        output = io.StringIO()
        with patch.dict(os.environ, {"JIRA_API_KEY": "highly-secret-token"}, clear=False), redirect_stdout(output):
            status = audit.main(["--epic", "EPIC-1", "--since", "2024-01-01T00:00:00Z", "--verbose"])

        self.assertEqual(status, 0)
        self.assertNotIn("highly-secret-token", output.getvalue())
        self.assertIn("2 candidate page(s)", output.getvalue())


if __name__ == "__main__":
    unittest.main()
