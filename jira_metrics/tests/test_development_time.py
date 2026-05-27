import argparse
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

# Add the parent directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
# pylint: disable=wrong-import-position,import-error
from development_time import (
    MISSING_IN_PROGRESS,
    NO_NEXT_STATUS,
    MonthlyDevelopmentTimeBucket,
    build_development_time_jql,
    calculate_monthly_development_time,
    calculate_percentile,
    find_first_development_window,
    get_development_time_team,
    main,
    parse_issue_types,
    process_development_time_metrics,
    show_development_time_metrics,
)

TEAM_FIELD_ID = "10075"


def create_changelog_entry(created, from_status, to_status):
    return SimpleNamespace(
        created=created,
        items=[
            SimpleNamespace(
                field="status",
                fromString=from_status,
                toString=to_status,
            )
        ],
    )


def create_issue(
    key="PROJ-1",
    histories=None,
    created="2024-01-02T10:00:00.000-0800",
    project_key="PROJ",
    team_value=None,
):
    fields = SimpleNamespace(
        created=created,
        project=SimpleNamespace(key=project_key),
    )
    if team_value is not None:
        setattr(fields, f"customfield_{TEAM_FIELD_ID}", SimpleNamespace(value=team_value))
    return SimpleNamespace(
        key=key,
        fields=fields,
        changelog=SimpleNamespace(histories=histories or []),
    )


class TestDevelopmentWindow(unittest.TestCase):
    def test_find_first_development_window_measures_first_in_progress_to_next_status(self):
        issue = create_issue(
            histories=[
                create_changelog_entry("2024-01-03T10:00:00.000-0800", "Open", "In Progress"),
                create_changelog_entry("2024-01-03T14:00:00.000-0800", "In Progress", "Code Review"),
            ]
        )

        result = find_first_development_window(issue)

        self.assertIsNone(result.reason)
        self.assertEqual(result.month_key, "2024-01")
        self.assertEqual(result.business_seconds, 4 * 3600)

    def test_find_first_development_window_ignores_later_in_progress_ranges(self):
        issue = create_issue(
            histories=[
                create_changelog_entry("2024-01-02T10:00:00.000-0800", "Open", "In Progress"),
                create_changelog_entry("2024-01-02T12:00:00.000-0800", "In Progress", "Blocked"),
                create_changelog_entry("2024-01-03T09:00:00.000-0800", "Blocked", "In Progress"),
                create_changelog_entry("2024-01-03T13:00:00.000-0800", "In Progress", "Code Review"),
            ]
        )

        result = find_first_development_window(issue)

        self.assertIsNone(result.reason)
        self.assertEqual(result.business_seconds, 2 * 3600)

    def test_find_first_development_window_counts_missing_in_progress_skip(self):
        issue = create_issue(
            histories=[
                create_changelog_entry("2024-02-02T10:00:00.000-0800", "Open", "Selected"),
                create_changelog_entry("2024-02-03T10:00:00.000-0800", "Selected", "Code Review"),
            ],
            created="2024-02-01T09:00:00.000-0800",
        )

        result = find_first_development_window(issue)

        self.assertEqual(result.reason, MISSING_IN_PROGRESS)
        self.assertEqual(result.month_key, "2024-02")
        self.assertIsNone(result.business_seconds)

    def test_find_first_development_window_counts_no_next_status_skip(self):
        issue = create_issue(
            histories=[
                create_changelog_entry("2024-03-02T10:00:00.000-0800", "Open", "In Progress"),
            ]
        )

        result = find_first_development_window(issue)

        self.assertEqual(result.reason, NO_NEXT_STATUS)
        self.assertEqual(result.month_key, "2024-03")
        self.assertIsNone(result.business_seconds)

    def test_find_first_development_window_matches_in_progress_case_insensitively(self):
        issue = create_issue(
            histories=[
                create_changelog_entry("2024-04-02T10:00:00.000-0800", "Open", "in progress"),
                create_changelog_entry("2024-04-02T11:30:00.000-0800", "in progress", "Blocked"),
            ]
        )

        result = find_first_development_window(issue)

        self.assertIsNone(result.reason)
        self.assertEqual(result.business_seconds, 90 * 60)

    def test_development_time_days_use_cycle_time_business_seconds_convention(self):
        issue = create_issue(
            histories=[
                create_changelog_entry("2024-01-05T14:00:00.000-0800", "Open", "In Progress"),
                create_changelog_entry("2024-01-08T10:00:00.000-0800", "In Progress", "Code Review"),
            ]
        )

        result = find_first_development_window(issue)
        bucket = MonthlyDevelopmentTimeBucket(development_times=[(result.business_seconds, result.issue_id)])
        metrics = process_development_time_metrics("All", {"2024-01": bucket})

        self.assertEqual(metrics[0]["Median Development Time (days)"], "2.00")


class TestIssueTypeFiltering(unittest.TestCase):
    def test_parse_issue_types_rejects_empty_values(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_issue_types(" , ")

    def test_parse_issue_types_splits_and_trims_values(self):
        self.assertEqual(parse_issue_types(" Story,Task, Bug "), ["Story", "Task", "Bug"])

    def test_build_development_time_jql_filters_to_provided_issue_types(self):
        jql = build_development_time_jql(
            ["ABC", "DEF"],
            ["Story", "Task", 'Bug "Escalated"'],
            "2024-01-01",
            "2024-12-31",
        )

        self.assertIn("project in (ABC, DEF)", jql)
        self.assertIn('issueType in ("Story", "Task", "Bug \\"Escalated\\"")', jql)
        self.assertIn('status CHANGED FROM "In Progress" DURING ("2024-01-01", "2024-12-31")', jql)
        self.assertIn('status != "In Progress"', jql)
        self.assertNotIn('status CHANGED TO "In Progress"', jql)
        self.assertNotIn("updated >= 2024-01-01", jql)
        self.assertNotIn("updated <= 2024-12-31", jql)
        self.assertNotIn("Task, Bug, Story, Spike", jql)

    def test_main_requires_issue_types(self):
        with patch.object(sys, "argv", ["development_time.py"]):
            with self.assertRaises(SystemExit):
                main()


class TestDevelopmentTimeTeam(unittest.TestCase):
    def test_get_development_time_team_uses_configured_team_field_when_present(self):
        issue = create_issue(team_value=" Platform ")

        with patch.dict(os.environ, {"CUSTOM_FIELD_TEAM": "10075"}):
            self.assertEqual(get_development_time_team(issue), "Platform")

    def test_get_development_time_team_uses_project_unknown_team_when_team_empty(self):
        issue = create_issue(team_value=" ", project_key="ENG")

        with patch.dict(os.environ, {"CUSTOM_FIELD_TEAM": "10075"}):
            self.assertEqual(get_development_time_team(issue), "ENG/unknown-team")

    def test_get_development_time_team_uses_project_unknown_team_when_team_field_missing(self):
        issue = create_issue(project_key="OPS")

        with patch.dict(os.environ, {"CUSTOM_FIELD_TEAM": "10075"}):
            self.assertEqual(get_development_time_team(issue), "OPS/unknown-team")

    def test_get_development_time_team_uses_issue_project_key_in_unknown_team_fallback(self):
        issue = create_issue(key="DATA-123", project_key="")

        with patch.dict(os.environ, {"CUSTOM_FIELD_TEAM": "10075"}):
            self.assertEqual(get_development_time_team(issue), "DATA/unknown-team")


class TestDevelopmentTimeAggregation(unittest.TestCase):
    @patch("development_time.get_tickets_from_jira")
    def test_aggregate_counts_missing_in_progress_by_created_month_for_all_and_team_rows(self, mock_get_tickets):
        issue = create_issue(
            key="PROJ-2",
            histories=[create_changelog_entry("2024-01-04T10:00:00.000-0800", "Open", "Selected")],
            created="2024-05-01T09:00:00.000-0800",
            team_value="Alpha",
        )
        mock_get_tickets.return_value = [issue]

        with patch.dict(os.environ, {"CUSTOM_FIELD_TEAM": "10075"}):
            metrics = calculate_monthly_development_time(["PROJ"], "2024-01-01", "2024-12-31", ["Story"])

        self.assertEqual(metrics["All"]["2024-05"].skipped_missing_in_progress, 1)
        self.assertEqual(metrics["Alpha"]["2024-05"].skipped_missing_in_progress, 1)

    @patch("development_time.get_tickets_from_jira")
    def test_aggregate_counts_no_next_status_by_first_in_progress_month_for_all_and_fallback_team_rows(
        self, mock_get_tickets
    ):
        issue = create_issue(
            key="OPS-2",
            histories=[create_changelog_entry("2024-06-04T10:00:00.000-0800", "Open", "In Progress")],
            project_key="OPS",
        )
        mock_get_tickets.return_value = [issue]

        with patch.dict(os.environ, {"CUSTOM_FIELD_TEAM": "10075"}):
            metrics = calculate_monthly_development_time(["OPS"], "2024-01-01", "2024-12-31", ["Bug"])

        self.assertEqual(metrics["All"]["2024-06"].skipped_no_next_status, 1)
        self.assertEqual(metrics["OPS/unknown-team"]["2024-06"].skipped_no_next_status, 1)

    @patch("development_time.get_tickets_from_jira")
    def test_calculate_monthly_development_time_uses_issue_type_jql(self, mock_get_tickets):
        mock_get_tickets.return_value = []

        calculate_monthly_development_time(["PROJ"], "2024-01-01", "2024-12-31", ["Bug"])

        mock_get_tickets.assert_called_once()
        self.assertIn('issueType in ("Bug")', mock_get_tickets.call_args.args[0])

    @patch("development_time.get_tickets_from_jira")
    def test_calculate_monthly_development_time_reports_only_result_months_in_date_range(self, mock_get_tickets):
        old_missing_issue = create_issue(
            key="PROJ-3",
            histories=[create_changelog_entry("2021-08-04T10:00:00.000-0800", "Open", "Selected")],
            created="2021-08-01T09:00:00.000-0800",
            team_value="Alpha",
        )
        old_window_issue = create_issue(
            key="PROJ-4",
            histories=[
                create_changelog_entry("2025-12-04T10:00:00.000-0800", "Open", "In Progress"),
                create_changelog_entry("2025-12-05T10:00:00.000-0800", "In Progress", "Done"),
            ],
            team_value="Alpha",
        )
        current_window_issue = create_issue(
            key="PROJ-5",
            histories=[
                create_changelog_entry("2026-01-04T10:00:00.000-0800", "Open", "In Progress"),
                create_changelog_entry("2026-01-05T10:00:00.000-0800", "In Progress", "Done"),
            ],
            team_value="Alpha",
        )
        mock_get_tickets.return_value = [old_missing_issue, old_window_issue, current_window_issue]

        with patch.dict(os.environ, {"CUSTOM_FIELD_TEAM": "10075"}):
            metrics = calculate_monthly_development_time(["PROJ"], "2026-01-01", "2026-12-31", ["Bug"])

        self.assertEqual(set(metrics["All"].keys()), {"2026-01"})
        self.assertEqual(metrics["All"]["2026-01"].skipped_missing_in_progress, 0)
        self.assertEqual(len(metrics["All"]["2026-01"].development_times), 1)

    @patch("development_time.get_tickets_from_jira")
    @patch("builtins.print")
    def test_calculate_monthly_development_time_prints_validation_jql(self, mock_print, mock_get_tickets):
        mock_get_tickets.return_value = []

        calculate_monthly_development_time(["PROJ"], "2024-01-01", "2024-12-31", ["Bug"])

        printed_lines = [call.args[0] for call in mock_print.call_args_list if call.args]
        self.assertIn(
            'JQL Query: project in (PROJ) AND status CHANGED FROM "In Progress" '
            'DURING ("2024-01-01", "2024-12-31") AND status != "In Progress" '
            'AND issueType in ("Bug") ORDER BY updated ASC\n',
            printed_lines,
        )

    def test_process_development_time_metrics_outputs_median_p75_ticket_and_skip_counts(self):
        bucket = MonthlyDevelopmentTimeBucket(
            development_times=[
                (1 * 8 * 3600, "PROJ-1"),
                (2 * 8 * 3600, "PROJ-2"),
                (4 * 8 * 3600, "PROJ-3"),
            ],
            skipped_missing_in_progress=2,
            skipped_no_next_status=1,
        )

        metrics = process_development_time_metrics("All", {"2024-07": bucket})

        self.assertEqual(
            metrics,
            [
                {
                    "Team": "All",
                    "Month": "2024-07",
                    "Median Development Time (days)": "2.00",
                    "P75 Development Time (days)": "3.00",
                    "Ticket Count": 3,
                    "Skipped: missing in-progress": 2,
                    "Skipped: no next status after in-progress": 1,
                }
            ],
        )

    @patch("builtins.print")
    def test_process_development_time_metrics_prints_average_of_monthly_medians(self, mock_print):
        january_bucket = MonthlyDevelopmentTimeBucket(
            development_times=[
                (1 * 8 * 3600, "PROJ-1"),
                (3 * 8 * 3600, "PROJ-2"),
            ]
        )
        february_bucket = MonthlyDevelopmentTimeBucket(
            development_times=[
                (4 * 8 * 3600, "PROJ-3"),
            ]
        )
        skip_only_bucket = MonthlyDevelopmentTimeBucket(skipped_missing_in_progress=1)

        process_development_time_metrics(
            "All",
            {
                "2024-01": january_bucket,
                "2024-02": february_bucket,
                "2024-03": skip_only_bucket,
            },
        )

        printed_lines = [call.args[0] for call in mock_print.call_args_list if call.args]
        self.assertIn(
            "Average monthly median Development Time for selected period: 3.00 days",
            printed_lines,
        )

    def test_show_development_time_metrics_includes_all_and_team_rows(self):
        all_bucket = MonthlyDevelopmentTimeBucket(
            development_times=[(8 * 3600, "PROJ-1")],
            skipped_missing_in_progress=1,
        )
        team_bucket = MonthlyDevelopmentTimeBucket(
            development_times=[(8 * 3600, "PROJ-1")],
            skipped_missing_in_progress=1,
        )
        metrics_by_team_month = {
            "All": {"2024-08": all_bucket},
            "PROJ/unknown-team": {"2024-08": team_bucket},
        }

        rows = show_development_time_metrics(False, metrics_by_team_month)

        self.assertEqual([row["Team"] for row in rows], ["All", "PROJ/unknown-team"])

    def test_calculate_percentile_uses_linear_interpolation(self):
        self.assertEqual(calculate_percentile([1.0, 2.0, 4.0], 0.50), 2.0)
        self.assertEqual(calculate_percentile([1.0, 2.0, 4.0], 0.75), 3.0)


if __name__ == "__main__":
    unittest.main()
