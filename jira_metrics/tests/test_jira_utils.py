import os
import sys
import unittest
from types import SimpleNamespace as StandardSimpleNamespace
from unittest.mock import patch

# Add the parent directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
# pylint: disable=wrong-import-position,import-error
import jira_utils
from jira_utils import (
    SimpleNamespace,
    calculate_total_time_in_status,
    convert_raw_issue_to_simple_object,
    get_completion_statuses,
    get_excluded_statuses,
    get_issue_created_month_key,
    get_project_key,
    get_status_transitions_chronological,
    get_team_or_project_unknown,
    is_month_key_in_date_range,
    month_key_from_jira_datetime,
    parse_jira_datetime,
)


TEAM_FIELD_ID = "10075"


def create_changelog_entry(created, from_status, to_status):
    return StandardSimpleNamespace(
        created=created,
        items=[
            StandardSimpleNamespace(
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
    fields = StandardSimpleNamespace(
        created=created,
        project=StandardSimpleNamespace(key=project_key),
    )
    if team_value is not None:
        setattr(fields, f"customfield_{TEAM_FIELD_ID}", StandardSimpleNamespace(value=team_value))
    return StandardSimpleNamespace(
        key=key,
        fields=fields,
        changelog=StandardSimpleNamespace(histories=histories or []),
    )


class TestCompletionStatuses(unittest.TestCase):
    def setUp(self):
        jira_utils.reset_status_caches()

    @patch.dict(os.environ, {"COMPLETION_STATUSES": "released, done, To Release"}, clear=False)
    def test_get_completion_statuses_parses_and_caches(self):
        statuses = get_completion_statuses()
        self.assertEqual(statuses, ["released", "done", "to release"])

        # Ensure cached value is returned on subsequent call
        statuses_again = get_completion_statuses()
        self.assertIs(statuses_again, statuses)

    @patch.dict(os.environ, {"EXCLUDED_STATUSES": "Closed, Cancelled , duplicate"}, clear=False)
    def test_get_excluded_statuses_parses_and_caches(self):
        statuses = get_excluded_statuses()
        self.assertEqual(statuses, ["closed", "cancelled", "duplicate"])

        statuses_again = get_excluded_statuses()
        self.assertIs(statuses_again, statuses)


class TestSafeGetNested(unittest.TestCase):
    def test_safe_get_nested(self):
        data = {"a": {"b": {"c": 123}}}
        self.assertEqual(jira_utils._safe_get_nested(data, "a", "b", "c"), 123)
        self.assertIsNone(jira_utils._safe_get_nested(data, "a", "missing", "c"))
        self.assertEqual(jira_utils._safe_get_nested(data, "a", "missing", default="fallback"), "fallback")


class TestConvertRawIssue(unittest.TestCase):
    def test_convert_raw_issue_minimal(self):
        raw_issue = {
            "key": "TEST-1",
            "fields": {
                "project": {"key": "PROJ", "name": "Project"},
                "status": {"name": "Released"},
                "priority": {"name": "P2 Moderate Issue"},
                "assignee": {"displayName": "Alice"},
                "issuelinks": [{"outwardIssue": {"key": "TEST-2"}}],
                "summary": "Example summary",
                "created": "2024-01-01T12:00:00.000+0000",
                "duedate": "2024-01-10",
                "resolutiondate": "2024-01-05T12:00:00.000+0000",
                "customfield_100": {"value": "Example team"},
            },
            "changelog": {"histories": []},
        }

        issue = convert_raw_issue_to_simple_object(raw_issue)
        self.assertEqual(issue.key, "TEST-1")
        self.assertEqual(issue.fields.project.key, "PROJ")
        self.assertEqual(issue.fields.project.name, "Project")
        self.assertEqual(issue.fields.status.name, "Released")
        self.assertEqual(issue.fields.priority.name, "P2 Moderate Issue")
        self.assertEqual(issue.fields.assignee.displayName, "Alice")
        self.assertEqual(issue.fields.summary, "Example summary")
        self.assertEqual(issue.fields.created, "2024-01-01T12:00:00.000+0000")
        self.assertEqual(issue.fields.duedate, "2024-01-10")
        self.assertEqual(issue.fields.resolutiondate, "2024-01-05T12:00:00.000+0000")
        self.assertEqual(issue.fields.customfield_100.value, "Example team")
        self.assertEqual(len(issue.fields.issuelinks), 1)
        self.assertEqual(issue.fields.issuelinks[0].outwardIssue.key, "TEST-2")
        self.assertIsInstance(issue.changelog, SimpleNamespace)

    def test_convert_raw_issue_missing_key(self):
        with self.assertRaises(ValueError):
            convert_raw_issue_to_simple_object({"fields": {}})


class TestJiraDateAndIssueHelpers(unittest.TestCase):
    def test_parse_jira_datetime_accepts_millis_and_non_millis_values(self):
        with_millis = parse_jira_datetime("2024-01-02T10:30:00.000-0800")
        without_millis = parse_jira_datetime("2024-01-02T10:30:00-0800")

        self.assertIsNotNone(with_millis)
        self.assertIsNotNone(without_millis)
        self.assertEqual(with_millis.strftime("%Y-%m-%d %H:%M"), "2024-01-02 10:30")
        self.assertEqual(without_millis.strftime("%Y-%m-%d %H:%M"), "2024-01-02 10:30")

    def test_month_key_from_jira_datetime_returns_month_or_unknown(self):
        self.assertEqual(month_key_from_jira_datetime("2024-03-02T10:00:00.000-0800"), "2024-03")
        self.assertEqual(month_key_from_jira_datetime("not a jira date"), "unknown")

    def test_get_issue_created_month_key_reads_created_field(self):
        issue = create_issue(created="2024-04-02T10:00:00.000-0800")

        self.assertEqual(get_issue_created_month_key(issue), "2024-04")

    def test_get_project_key_prefers_project_field_and_falls_back_to_issue_key(self):
        issue_with_project = create_issue(project_key=" proj ")
        issue_with_key_only = create_issue(key="DATA-123", project_key="")

        self.assertEqual(get_project_key(issue_with_project), "PROJ")
        self.assertEqual(get_project_key(issue_with_key_only), "DATA")

    def test_is_month_key_in_date_range_rejects_invalid_and_outside_months(self):
        self.assertTrue(is_month_key_in_date_range("2024-06", "2024-01-01", "2024-12-31"))
        self.assertFalse(is_month_key_in_date_range("2023-12", "2024-01-01", "2024-12-31"))
        self.assertFalse(is_month_key_in_date_range("unknown", "2024-01-01", "2024-12-31"))


class TestJiraTeamHelpers(unittest.TestCase):
    def test_get_team_or_project_unknown_uses_configured_team_field_when_present(self):
        issue = create_issue(team_value=" Platform ")

        with patch.dict(os.environ, {"CUSTOM_FIELD_TEAM": TEAM_FIELD_ID}):
            self.assertEqual(get_team_or_project_unknown(issue), "Platform")

    def test_get_team_or_project_unknown_uses_project_unknown_team_when_team_empty(self):
        issue = create_issue(team_value=" ", project_key="ABC")

        with patch.dict(os.environ, {"CUSTOM_FIELD_TEAM": TEAM_FIELD_ID}):
            self.assertEqual(get_team_or_project_unknown(issue), "ABC/unknown-team")

    def test_get_team_or_project_unknown_uses_issue_project_key_fallback(self):
        issue = create_issue(key="DATA-123", project_key="")

        with patch.dict(os.environ, {"CUSTOM_FIELD_TEAM": TEAM_FIELD_ID}):
            self.assertEqual(get_team_or_project_unknown(issue), "DATA/unknown-team")


class TestStatusTransitionHelpers(unittest.TestCase):
    def test_get_status_transitions_chronological_returns_oldest_first(self):
        issue = create_issue(
            histories=[
                create_changelog_entry("2024-01-03T10:00:00.000-0800", "In Progress", "Done"),
                create_changelog_entry("2024-01-02T10:00:00.000-0800", "Open", "In Progress"),
            ]
        )

        transitions = get_status_transitions_chronological(issue)

        self.assertEqual([transition.status for transition in transitions], ["In Progress", "Done"])
        self.assertEqual(transitions[0].timestamp.strftime("%Y-%m-%d %H:%M"), "2024-01-02 10:00")

    def test_calculate_total_time_in_status_sums_completed_intervals(self):
        issue = create_issue(
            histories=[
                create_changelog_entry("2024-01-02T10:00:00.000-0800", "Open", "Review"),
                create_changelog_entry("2024-01-02T12:00:00.000-0800", "Review", "Blocked"),
                create_changelog_entry("2024-01-03T09:00:00.000-0800", "Blocked", "review"),
                create_changelog_entry("2024-01-03T13:00:00.000-0800", "review", "Done"),
            ]
        )

        result = calculate_total_time_in_status(
            issue,
            "review",
            lambda start, end: (end - start).total_seconds(),
        )

        self.assertTrue(result.saw_status)
        self.assertEqual(result.completed_intervals, 2)
        self.assertEqual(result.total_seconds, 6 * 3600)
        self.assertEqual(result.last_exit_timestamp.strftime("%Y-%m-%d %H:%M"), "2024-01-03 13:00")
        self.assertIsNone(result.open_start_timestamp)

    def test_calculate_total_time_in_status_reports_open_interval_without_exit(self):
        issue = create_issue(
            histories=[
                create_changelog_entry("2024-01-02T10:00:00.000-0800", "Open", "Selected"),
                create_changelog_entry("2024-01-03T09:00:00.000-0800", "Selected", "In Progress"),
            ]
        )

        result = calculate_total_time_in_status(
            issue,
            "In Progress",
            lambda start, end: (end - start).total_seconds(),
        )

        self.assertTrue(result.saw_status)
        self.assertEqual(result.completed_intervals, 0)
        self.assertEqual(result.total_seconds, 0)
        self.assertEqual(result.open_start_timestamp.strftime("%Y-%m-%d %H:%M"), "2024-01-03 09:00")
