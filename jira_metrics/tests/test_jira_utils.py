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
    fetch_complete_changelogs,
    get_completion_statuses,
    get_excluded_statuses,
    get_issue_created_month_key,
    get_jira_field_metadata,
    get_project_key,
    get_status_transitions_chronological,
    get_team_or_project_unknown,
    is_month_key_in_date_range,
    month_key_from_jira_datetime,
    parse_jira_datetime,
    search_jira_issues_raw,
)


TEAM_FIELD_ID = "10075"
REST_ENV = {
    "JIRA_LINK": "https://jira.example.test",
    "USER_EMAIL": "user@example.test",
    "JIRA_API_KEY": "test-token",
}


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, ValueError):
            raise self._payload
        return self._payload


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


class TestRawJiraRetrieval(unittest.TestCase):
    @patch.dict(os.environ, REST_ENV, clear=False)
    @patch("jira_utils.requests.get")
    def test_search_jira_issues_raw_paginates_next_page_tokens(self, mock_get):
        mock_get.side_effect = [
            FakeResponse(200, {"issues": [{"id": "1", "key": "A-1"}], "nextPageToken": "next-1"}),
            FakeResponse(200, {"issues": [], "nextPageToken": "next-2"}),
            FakeResponse(200, {"issues": [{"id": "2", "key": "A-2"}], "isLast": True}),
        ]

        result = search_jira_issues_raw("updated >= '2024-01-01'", ["summary"])

        self.assertTrue(result.complete)
        self.assertEqual([issue["key"] for issue in result.issues], ["A-1", "A-2"])
        self.assertEqual(result.page_count, 3)
        self.assertNotIn("nextPageToken", mock_get.call_args_list[0].kwargs["params"])
        self.assertEqual(mock_get.call_args_list[1].kwargs["params"]["nextPageToken"], "next-1")
        self.assertEqual(mock_get.call_args_list[2].kwargs["params"]["nextPageToken"], "next-2")

    @patch.dict(os.environ, REST_ENV, clear=False)
    @patch("jira_utils.requests.get")
    def test_search_result_surfaces_partial_page_failure(self, mock_get):
        mock_get.side_effect = [
            FakeResponse(200, {"issues": [{"id": "1", "key": "A-1"}], "nextPageToken": "next"}),
            FakeResponse(403, {}),
        ]

        result = search_jira_issues_raw("updated >= '2024-01-01'", ["summary"])

        self.assertFalse(result.complete)
        self.assertEqual([issue["key"] for issue in result.issues], ["A-1"])
        self.assertIn("page 2 failed", result.limitations[0])

    @patch.dict(os.environ, REST_ENV, clear=False)
    @patch("jira_utils.requests.get")
    def test_get_jira_field_metadata_retains_ids_and_names(self, mock_get):
        mock_get.return_value = FakeResponse(
            200,
            [{"id": "parent", "name": "Parent"}, {"id": "customfield_1", "name": "Epic Link"}],
        )

        result = get_jira_field_metadata()

        self.assertTrue(result.complete)
        self.assertEqual(result.fields[1]["id"], "customfield_1")
        self.assertEqual(result.fields[1]["name"], "Epic Link")

    @patch.dict(os.environ, REST_ENV, clear=False)
    @patch("jira_utils.requests.post")
    def test_bulk_changelog_fetch_splits_issue_batches_at_1000(self, mock_post):
        def respond(_url, **kwargs):
            containers = [
                {"issueId": issue_key, "changeHistories": []} for issue_key in kwargs["json"]["issueIdsOrKeys"]
            ]
            return FakeResponse(200, {"issueChangeLogs": containers})

        mock_post.side_effect = respond
        issue_keys = [f"PROJ-{number}" for number in range(1, 1002)]

        result = fetch_complete_changelogs(issue_keys)

        self.assertTrue(result.complete)
        self.assertEqual(mock_post.call_count, 2)
        self.assertEqual(len(mock_post.call_args_list[0].kwargs["json"]["issueIdsOrKeys"]), 1000)
        self.assertEqual(len(mock_post.call_args_list[1].kwargs["json"]["issueIdsOrKeys"]), 1)

    @patch.dict(os.environ, REST_ENV, clear=False)
    @patch("jira_utils.requests.post")
    def test_bulk_changelog_fetch_paginates_every_next_page_token(self, mock_post):
        history = {
            "id": "h-1",
            "created": "2024-01-01T00:00:00.000+0000",
            "author": {"displayName": "Alice", "accountId": "account-1"},
            "items": [
                {
                    "field": "Parent",
                    "fieldId": "parent",
                    "from": None,
                    "fromString": None,
                    "to": "100",
                    "toString": "EPIC-1",
                }
            ],
        }
        mock_post.side_effect = [
            FakeResponse(
                200,
                {
                    "issueChangeLogs": [{"issueId": "1", "changeHistories": [history]}],
                    "nextPageToken": "page-2",
                },
            ),
            FakeResponse(200, {"issueChangeLogs": [{"issueId": "1", "changeHistories": []}]}),
        ]

        result = fetch_complete_changelogs(["1"], {"1": "PROJ-1"})

        self.assertTrue(result.complete)
        self.assertEqual(result.method, "bulk")
        self.assertEqual(mock_post.call_args_list[1].kwargs["json"]["nextPageToken"], "page-2")
        retained = result.records_by_issue["PROJ-1"][0]
        self.assertEqual(retained["author"]["accountId"], "account-1")
        self.assertEqual(retained["items"][0]["to"], "100")

    @patch.dict(os.environ, REST_ENV, clear=False)
    @patch("jira_utils.requests.get")
    @patch("jira_utils.requests.post")
    def test_bulk_unavailable_falls_back_to_paginated_per_issue_fetch(self, mock_post, mock_get):
        mock_post.return_value = FakeResponse(404, {})
        mock_get.side_effect = [
            FakeResponse(200, {"values": [{"id": "one"}], "startAt": 0, "maxResults": 1, "total": 2}),
            FakeResponse(200, {"values": [{"id": "two"}], "startAt": 1, "maxResults": 1, "total": 2}),
        ]

        result = fetch_complete_changelogs(["PROJ-1"])

        self.assertTrue(result.complete)
        self.assertEqual(result.method, "per-issue fallback")
        self.assertEqual([item["id"] for item in result.records_by_issue["PROJ-1"]], ["one", "two"])
        self.assertEqual(mock_get.call_args_list[1].kwargs["params"]["startAt"], 1)

    @patch.dict(os.environ, REST_ENV, clear=False)
    @patch("jira_utils.requests.get")
    @patch("jira_utils.requests.post")
    def test_per_issue_fallback_rejects_repeated_or_regressed_pages(self, mock_post, mock_get):
        mock_post.return_value = FakeResponse(404, {})

        for returned_start in (0, 1):
            with self.subTest(returned_start=returned_start):
                mock_get.reset_mock()
                mock_get.side_effect = [
                    FakeResponse(
                        200,
                        {
                            "values": [{"id": "one"}, {"id": "two"}],
                            "startAt": 0,
                            "total": 3,
                        },
                    ),
                    FakeResponse(
                        200,
                        {
                            "values": [{"id": "repeated"}],
                            "startAt": returned_start,
                            "total": 3,
                        },
                    ),
                ]

                result = fetch_complete_changelogs(["PROJ-1"])

                self.assertFalse(result.complete)
                self.assertEqual(mock_get.call_count, 2)
                self.assertIn("requested startAt 2", " ".join(result.limitations))
                self.assertIn(f"returned {returned_start}", " ".join(result.limitations))

    @patch.dict(os.environ, REST_ENV, clear=False)
    @patch("jira_utils.requests.get")
    @patch("jira_utils.requests.post")
    def test_per_issue_fallback_rejects_contradictory_terminal_metadata(self, mock_post, mock_get):
        mock_post.return_value = FakeResponse(404, {})

        contradictory_pages = (
            {"values": [{"id": "one"}], "startAt": 0, "total": 2, "isLast": True},
            {"values": [{"id": "one"}], "startAt": 0, "total": 1, "isLast": False},
        )
        for page in contradictory_pages:
            with self.subTest(page=page):
                mock_get.reset_mock()
                mock_get.return_value = FakeResponse(200, page)

                result = fetch_complete_changelogs(["PROJ-1"])

                self.assertFalse(result.complete)
                self.assertEqual(mock_get.call_count, 1)
                self.assertIn("contradictory pagination metadata", " ".join(result.limitations))

    @patch.dict(os.environ, REST_ENV, clear=False)
    @patch("jira_utils.requests.get")
    @patch("jira_utils.requests.post")
    def test_per_issue_fallback_requires_reliable_page_termination(self, mock_post, mock_get):
        mock_post.return_value = FakeResponse(404, {})
        mock_get.return_value = FakeResponse(200, {"values": [], "startAt": 0, "isLast": False})

        result = fetch_complete_changelogs(["PROJ-1"])

        self.assertFalse(result.complete)
        self.assertIn("before the final page", " ".join(result.limitations))

    @patch.dict(os.environ, REST_ENV, clear=False)
    @patch("jira_utils.requests.get")
    @patch("jira_utils.requests.post")
    def test_later_bulk_page_failure_preserves_records_and_falls_back_without_duplicates(self, mock_post, mock_get):
        history = {"id": "one", "created": "2024-01-01T00:00:00.000+0000", "items": []}
        mock_post.side_effect = [
            FakeResponse(
                200,
                {
                    "issueChangeLogs": [{"issueId": "PROJ-1", "changeHistories": [history]}],
                    "nextPageToken": "next",
                },
            ),
            FakeResponse(403, {}),
        ]
        mock_get.return_value = FakeResponse(
            200,
            {"values": [history], "startAt": 0, "total": 1, "isLast": True},
        )

        result = fetch_complete_changelogs(["PROJ-1"])

        self.assertFalse(result.complete)
        self.assertEqual(result.method, "mixed bulk and per-issue fallback")
        self.assertEqual(result.records_by_issue["PROJ-1"], [history])
        self.assertIn("Bulk changelog page failed", " ".join(result.limitations))

    @patch.dict(os.environ, REST_ENV, clear=False)
    @patch("jira_utils.requests.get")
    @patch("jira_utils.requests.post")
    def test_missing_requested_issue_uses_fallback_and_unresolved_failure_is_incomplete(self, mock_post, mock_get):
        mock_post.return_value = FakeResponse(
            200,
            {"issueChangeLogs": [{"issueId": "PROJ-1", "changeHistories": []}]},
        )
        mock_get.return_value = FakeResponse(403, {})

        result = fetch_complete_changelogs(["PROJ-1", "PROJ-2"])

        self.assertFalse(result.complete)
        self.assertEqual(mock_get.call_count, 1)
        self.assertIn("PROJ-2", " ".join(result.limitations))
