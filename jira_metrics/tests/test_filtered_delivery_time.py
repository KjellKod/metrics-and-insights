import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
# pylint: disable=wrong-import-position,import-error
import filtered_delivery_time as report
from jira_utils import ChangelogFetchResult, JiraSearchResult


def issue(key="PROJ-1", issue_type="Story", labels=None, field_value=None):
    fields = {
        "issuetype": {"name": issue_type},
        "labels": labels or [],
    }
    if field_value is not None:
        fields["customfield_12345"] = {"value": field_value}
    return {"id": key.replace("PROJ-", ""), "key": key, "fields": fields}


def history(history_id, created, items):
    return {"id": str(history_id), "created": created, "items": items}


def status_item(from_status, to_status):
    return {"field": "status", "fromString": from_status, "toString": to_status}


def label_item(from_labels, to_labels):
    return {"field": "labels", "fromString": from_labels, "toString": to_labels}


def field_item(from_value, to_value):
    return {
        "field": "customfield_12345",
        "fieldId": "customfield_12345",
        "fromString": from_value,
        "toString": to_value,
    }


def issue_type_item(from_value, to_value):
    return {"field": "issuetype", "fromString": from_value, "toString": to_value}


def config(**overrides):
    base = {
        "year": 2026,
        "issue_types": frozenset({"story", "task", "bug"}),
        "start_statuses": frozenset({"in progress", "implementing"}),
        "end_statuses": frozenset({"done", "released"}),
        "label": "example-label",
        "field_id": None,
        "field_value": None,
        "projects": ("PROJ",),
        "output_dir": Path("reports/filtered-delivery-time"),
        "write_csv": True,
    }
    base.update(overrides)
    return report.ReportConfig(**base)


class TestCliValidation(unittest.TestCase):
    def test_parse_args_requires_selector(self):
        with self.assertRaises(SystemExit):
            report.parse_args(
                [
                    "--year",
                    "2026",
                    "--issue-types",
                    "Story",
                    "--start-statuses",
                    "In Progress",
                ]
            )

    def test_parse_args_requires_field_pair(self):
        with self.assertRaises(SystemExit):
            report.parse_args(
                [
                    "--year",
                    "2026",
                    "--issue-types",
                    "Story",
                    "--start-statuses",
                    "In Progress",
                    "--field-value",
                    "Bugs",
                ]
            )

    def test_parse_args_rejects_empty_csv_values(self):
        with self.assertRaises(SystemExit):
            report.parse_args(
                [
                    "--year",
                    "2026",
                    "--issue-types",
                    "Story,",
                    "--start-statuses",
                    "In Progress",
                    "--label",
                    "example-label",
                ]
            )

    def test_parse_args_rejects_blank_label_selector(self):
        with self.assertRaises(SystemExit):
            report.parse_args(
                [
                    "--year",
                    "2026",
                    "--issue-types",
                    "Story",
                    "--start-statuses",
                    "In Progress",
                    "--label",
                    "   ",
                ]
            )

    def test_parse_args_rejects_blank_field_value_selector(self):
        with self.assertRaises(SystemExit):
            report.parse_args(
                [
                    "--year",
                    "2026",
                    "--issue-types",
                    "Story",
                    "--start-statuses",
                    "In Progress",
                    "--field-id-env",
                    "CUSTOM_FIELD_TICKET_CATEGORY",
                    "--field-value",
                    "   ",
                ]
            )

    def test_resolve_field_id_requires_numeric_env_value(self):
        with patch.dict(os.environ, {"CUSTOM_FIELD_TICKET_CATEGORY": "abc"}, clear=False):
            with self.assertRaisesRegex(report.ReportError, "numeric"):
                report.resolve_field_id("CUSTOM_FIELD_TICKET_CATEGORY")

    def test_resolve_projects_requires_env_unless_all_projects(self):
        args = report.parse_args(
            [
                "--year",
                "2026",
                "--issue-types",
                "Story",
                "--start-statuses",
                "In Progress",
                "--label",
                "example-label",
            ]
        )
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(report.ReportError, "JIRA_PROJECTS"):
                report.resolve_projects(args)


class TestCandidateJql(unittest.TestCase):
    def test_candidate_jql_pads_year_window_and_omits_selectors(self):
        jql = report.build_completion_candidate_jql(
            2026,
            frozenset({"story"}),
            frozenset({"done"}),
            ("PROJ",),
        )

        self.assertIn('"2025-12-30"', jql)
        self.assertIn('"2027-01-02"', jql)
        self.assertNotIn("labels", jql.casefold())
        self.assertNotIn("customfield", jql.casefold())


class TestHistoricalSelection(unittest.TestCase):
    def test_label_selector_uses_value_at_completion(self):
        histories = report.normalize_changelog(
            [
                history(1, "2026-03-01T10:00:00.000-0700", [status_item("Open", "In Progress")]),
                history(2, "2026-03-02T10:00:00.000-0700", [status_item("In Progress", "Done")]),
                history(3, "2026-03-03T10:00:00.000-0700", [label_item("", "example-label")]),
            ]
        )

        result = report.select_ticket_cycles(issue(labels=["example-label"]), histories, config())

        self.assertIsNone(result)

    def test_label_removed_after_completion_still_matches_completion_snapshot(self):
        histories = report.normalize_changelog(
            [
                history(1, "2026-03-01T10:00:00.000-0700", [status_item("Open", "In Progress")]),
                history(2, "2026-03-02T10:00:00.000-0700", [status_item("In Progress", "Done")]),
                history(3, "2026-03-03T10:00:00.000-0700", [label_item("example-label", "")]),
            ]
        )

        result = report.select_ticket_cycles(issue(labels=[]), histories, config())

        self.assertIsNotNone(result)

    def test_field_selector_uses_value_at_completion(self):
        histories = report.normalize_changelog(
            [
                history(1, "2026-03-01T10:00:00.000-0700", [status_item("Open", "In Progress")]),
                history(2, "2026-03-02T10:00:00.000-0700", [status_item("In Progress", "Done")]),
                history(3, "2026-03-03T10:00:00.000-0700", [field_item("Other", "Bugs")]),
            ]
        )

        result = report.select_ticket_cycles(
            issue(labels=["example-label"], field_value="Bugs"),
            histories,
            config(field_id="12345", field_value="Bugs", label=None),
        )

        self.assertIsNone(result)

    def test_field_value_removed_after_completion_still_matches_completion_snapshot(self):
        histories = report.normalize_changelog(
            [
                history(1, "2026-03-01T10:00:00.000-0700", [status_item("Open", "In Progress")]),
                history(2, "2026-03-02T10:00:00.000-0700", [status_item("In Progress", "Done")]),
                history(3, "2026-03-03T10:00:00.000-0700", [field_item("Bugs", "Other")]),
            ]
        )

        result = report.select_ticket_cycles(
            issue(labels=["example-label"], field_value="Other"),
            histories,
            config(field_id="12345", field_value="Bugs", label=None),
        )

        self.assertIsNotNone(result)

    def test_combined_selectors_require_both_at_same_completion(self):
        histories = report.normalize_changelog(
            [
                history(1, "2026-03-01T10:00:00.000-0700", [status_item("Open", "In Progress")]),
                history(2, "2026-03-02T10:00:00.000-0700", [status_item("In Progress", "Done")]),
                history(3, "2026-03-03T10:00:00.000-0700", [field_item("Other", "Bugs")]),
            ]
        )

        result = report.select_ticket_cycles(
            issue(labels=["example-label"], field_value="Bugs"),
            histories,
            config(field_id="12345", field_value="Bugs"),
        )

        self.assertIsNone(result)

    def test_issue_type_uses_value_at_completion(self):
        histories = report.normalize_changelog(
            [
                history(1, "2026-03-01T10:00:00.000-0700", [status_item("Open", "In Progress")]),
                history(2, "2026-03-02T10:00:00.000-0700", [status_item("In Progress", "Done")]),
                history(3, "2026-03-03T10:00:00.000-0700", [issue_type_item("Spike", "Story")]),
            ]
        )

        result = report.select_ticket_cycles(issue(labels=["example-label"]), histories, config())

        self.assertIsNone(result)


class TestCycleModel(unittest.TestCase):
    def test_reconstruct_cycles_ignores_start_to_start_moves_and_status_case(self):
        histories = report.normalize_changelog(
            [
                history(1, "2026-03-02T09:00:00.000-0700", [status_item("Open", "in progress")]),
                history(2, "2026-03-02T10:00:00.000-0700", [status_item("In Progress", "IMPLEMENTING")]),
                history(3, "2026-03-02T11:00:00.000-0700", [status_item("Implementing", "done")]),
            ]
        )

        cycles = report.reconstruct_cycles(histories, frozenset({"in progress", "implementing"}), frozenset({"done"}), 2026)

        self.assertEqual(len(cycles), 1)
        self.assertEqual(cycles[0].business_seconds, 2 * 3600)

    def test_reconstruct_cycles_ignores_end_to_end_moves(self):
        histories = report.normalize_changelog(
            [
                history(1, "2026-03-01T09:00:00.000-0700", [status_item("Open", "In Progress")]),
                history(2, "2026-03-01T10:00:00.000-0700", [status_item("In Progress", "Done")]),
                history(3, "2026-03-01T11:00:00.000-0700", [status_item("Done", "Released")]),
            ]
        )

        cycles = report.reconstruct_cycles(histories, frozenset({"in progress"}), frozenset({"done", "released"}), 2026)

        self.assertEqual(len(cycles), 1)

    def test_reopened_cycle_counts_separately_and_excludes_idle_time(self):
        histories = report.normalize_changelog(
            [
                history(1, "2026-03-02T09:00:00.000-0700", [status_item("Open", "In Progress")]),
                history(2, "2026-03-02T10:00:00.000-0700", [status_item("In Progress", "Done")]),
                history(3, "2026-03-03T09:00:00.000-0700", [status_item("Done", "In Progress")]),
                history(4, "2026-03-03T11:00:00.000-0700", [status_item("In Progress", "Done")]),
            ]
        )

        result = report.select_ticket_cycles(issue(labels=["example-label"]), histories, config())

        self.assertEqual(result.completed_cycles, 2)
        self.assertEqual(result.reopened_cycles, 1)
        self.assertEqual(result.total_business_seconds, 3 * 3600)

    def test_completion_without_start_counts_missing_start_without_duration(self):
        histories = report.normalize_changelog(
            [history(1, "2026-03-02T10:00:00.000-0700", [status_item("Open", "Done")])]
        )

        result = report.select_ticket_cycles(issue(labels=["example-label"]), histories, config())

        self.assertEqual(result.completed_cycles, 1)
        self.assertEqual(result.missing_start_cycles, 1)
        self.assertEqual(result.total_business_seconds, 0)

    def test_cycle_started_previous_year_counts_when_completed_in_year(self):
        histories = report.normalize_changelog(
            [
                history(1, "2025-12-31T10:00:00.000-0700", [status_item("Open", "In Progress")]),
                history(2, "2026-01-02T10:00:00.000-0700", [status_item("In Progress", "Done")]),
            ]
        )

        result = report.select_ticket_cycles(issue(labels=["example-label"]), histories, config())

        self.assertEqual(result.completed_cycles, 1)
        self.assertGreater(result.total_business_seconds, 0)

    def test_completion_year_uses_own_offset_at_december_january_boundary(self):
        histories = report.normalize_changelog(
            [
                history(1, "2025-12-31T23:00:00.000-0700", [status_item("Open", "In Progress")]),
                history(2, "2025-12-31T23:30:00.000-0700", [status_item("In Progress", "Done")]),
                history(3, "2026-01-01T00:00:00.000-0700", [status_item("Done", "In Progress")]),
                history(4, "2026-01-01T00:30:00.000-0700", [status_item("In Progress", "Done")]),
            ]
        )

        cycles = report.reconstruct_cycles(histories, frozenset({"in progress"}), frozenset({"done"}), 2026)

        self.assertEqual(len(cycles), 1)
        self.assertEqual(cycles[0].completion_timestamp.strftime("%Y-%m-%d %H:%M %z"), "2026-01-01 00:30 -0700")


class TestAggregationAndOutput(unittest.TestCase):
    def ticket_with_days(self, key, days):
        return report.TicketResult(
            issue_key=key,
            issue_id=key.rsplit("-", 1)[-1],
            latest_completion=report.parse_jira_timestamp("2026-01-02T10:00:00.000-0700"),
            latest_issue_type="Story",
            matched_label="example-label",
            matched_field_value="",
            completed_cycles=1,
            reopened_cycles=0,
            measured_cycles=1,
            missing_start_cycles=0,
            total_business_seconds=days * report.SECONDS_TO_HOURS * report.HOURS_TO_DAYS,
            cycle_evidence=(),
        )

    def test_summary_percentiles_use_linear_interpolation(self):
        rows = report.aggregate_monthly(
            [
                self.ticket_with_days("PROJ-1", 1.0),
                self.ticket_with_days("PROJ-2", 2.0),
                self.ticket_with_days("PROJ-3", 4.0),
            ],
            2026,
        )

        self.assertEqual(rows[0].median_business_days, 2.0)
        self.assertAlmostEqual(rows[0].p85_business_days, 3.4)
        self.assertGreaterEqual(rows[0].p85_business_days, rows[0].median_business_days)

    def test_latest_matching_completion_month_receives_ticket_attribution(self):
        older = report.CycleResult(
            completion_timestamp=report.parse_jira_timestamp("2026-03-31T23:30:00.000-0700"),
            started_at=None,
            business_seconds=3600,
            missing_start=False,
            reopened=False,
        )
        latest = report.CycleResult(
            completion_timestamp=report.parse_jira_timestamp("2026-04-01T00:30:00.000-0700"),
            started_at=None,
            business_seconds=7200,
            missing_start=False,
            reopened=True,
        )
        ticket = report.TicketResult(
            issue_key="PROJ-1",
            issue_id="1",
            latest_completion=latest.completion_timestamp,
            latest_issue_type="Story",
            matched_label="example-label",
            matched_field_value="",
            completed_cycles=2,
            reopened_cycles=1,
            measured_cycles=2,
            missing_start_cycles=0,
            total_business_seconds=older.business_seconds + latest.business_seconds,
            cycle_evidence=(),
        )

        rows = report.aggregate_monthly([ticket], 2026)

        self.assertEqual(rows[2].completed_tickets, 0)
        self.assertEqual(rows[3].completed_tickets, 1)

    def test_aggregate_monthly_includes_all_12_months_and_data_complete(self):
        rows = report.aggregate_monthly([], 2026)

        self.assertEqual(len(rows), 12)
        self.assertTrue(all(row.data_complete for row in rows))
        self.assertEqual(rows[0].median_business_days, 0)

    def test_write_outputs_creates_summary_and_detail_csvs_and_safe_cells(self):
        ticket = report.TicketResult(
            issue_key="=PROJ-1",
            issue_id="1",
            latest_completion=report.parse_jira_timestamp("2026-01-02T10:00:00.000-0700"),
            latest_issue_type="Story",
            matched_label="example-label",
            matched_field_value="",
            completed_cycles=1,
            reopened_cycles=0,
            measured_cycles=1,
            missing_start_cycles=0,
            total_business_seconds=3600,
            cycle_evidence=("{}",),
        )
        with self.subTest("files"):
            with TemporaryDirectory() as directory:
                summary_path, detail_path = report.write_outputs(
                    report.aggregate_monthly([ticket], 2026),
                    [ticket],
                    Path(directory),
                    2026,
                )
                self.assertTrue(summary_path.exists())
                self.assertTrue(detail_path.exists())
                self.assertIn("'=PROJ-1", detail_path.read_text(encoding="utf-8"))


class TestFailClosed(unittest.TestCase):
    def test_run_report_prints_jql_before_search(self):
        expected_jql = report.build_completion_candidate_jql(
            2026,
            frozenset({"story", "task", "bug"}),
            frozenset({"done", "released"}),
            ("PROJ",),
        )
        events = []

        def record_print(*values, **_kwargs):
            events.append(("print", " ".join(str(value) for value in values)))

        def record_search(jql, _fields):
            events.append(("search", jql))
            return JiraSearchResult([], False, ["expected stop"], 1)

        with patch("builtins.print", side_effect=record_print):
            with patch("filtered_delivery_time.search_jira_issues_raw", side_effect=record_search):
                with self.assertRaises(report.ReportError):
                    report.run_report(config(output_dir=Path("/tmp/unused")))

        self.assertEqual(
            events[:3],
            [("print", "Jira JQL:"), ("print", expected_jql), ("search", expected_jql)],
        )

    def test_run_exits_before_csv_when_candidate_search_incomplete(self):
        with patch("filtered_delivery_time.search_jira_issues_raw") as search:
            search.return_value = JiraSearchResult([], False, ["page failed"], 1)

            with self.assertRaisesRegex(report.ReportError, "Candidate search"):
                report.run_report(config(output_dir=Path("/tmp/unused")))

    def test_run_exits_before_csv_when_changelog_fetch_incomplete(self):
        raw_issue = issue(labels=["example-label"])
        with patch("filtered_delivery_time.search_jira_issues_raw") as search:
            with patch("filtered_delivery_time.fetch_complete_changelogs") as changelog:
                search.return_value = JiraSearchResult([raw_issue], True)
                changelog.return_value = ChangelogFetchResult({}, "bulk", False, ["missing page"])

                with self.assertRaisesRegex(report.ReportError, "Changelog"):
                    report.run_report(config(output_dir=Path("/tmp/unused")))

    def test_run_exits_before_csv_when_calculation_fails_after_successful_retrieval(self):
        raw_issue = issue(labels=["example-label"])
        with patch("filtered_delivery_time.search_jira_issues_raw") as search:
            with patch("filtered_delivery_time.fetch_complete_changelogs") as changelog:
                with patch("filtered_delivery_time.select_ticket_cycles", side_effect=ValueError("bad timestamp")):
                    search.return_value = JiraSearchResult([raw_issue], True)
                    changelog.return_value = ChangelogFetchResult({"PROJ-1": []}, "bulk", True)

                    with self.assertRaisesRegex(ValueError, "bad timestamp"):
                        report.run_report(config(output_dir=Path("/tmp/unused")))

    def test_run_report_deduplicates_duplicate_search_issue_keys(self):
        raw_issue = issue(labels=["example-label"])
        histories = [history(1, "2026-03-02T10:00:00.000-0700", [status_item("Open", "Done")])]
        with patch("filtered_delivery_time.search_jira_issues_raw") as search:
            with patch("filtered_delivery_time.fetch_complete_changelogs") as changelog:
                search.return_value = JiraSearchResult([raw_issue, raw_issue], True)
                changelog.return_value = ChangelogFetchResult({"PROJ-1": histories}, "bulk", True)

                _, detail_rows, _ = report.run_report(config(write_csv=False))

        self.assertEqual(len(detail_rows), 1)
        self.assertEqual(detail_rows[0].issue_key, "PROJ-1")


if __name__ == "__main__":
    unittest.main()
