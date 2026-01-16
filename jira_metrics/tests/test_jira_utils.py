import os
import sys
import unittest
from unittest.mock import patch

# Add the parent directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
# pylint: disable=wrong-import-position,import-error
import jira_utils
from jira_utils import SimpleNamespace, convert_raw_issue_to_simple_object, get_completion_statuses, get_excluded_statuses


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
                "assignee": {"displayName": "Alice"},
                "issuelinks": [{"outwardIssue": {"key": "TEST-2"}}],
                "summary": "Example summary",
                "customfield_100": {"value": "Platform"},
            },
            "changelog": {"histories": []},
        }

        issue = convert_raw_issue_to_simple_object(raw_issue)
        self.assertEqual(issue.key, "TEST-1")
        self.assertEqual(issue.fields.project.key, "PROJ")
        self.assertEqual(issue.fields.project.name, "Project")
        self.assertEqual(issue.fields.status.name, "Released")
        self.assertEqual(issue.fields.assignee.displayName, "Alice")
        self.assertEqual(issue.fields.summary, "Example summary")
        self.assertEqual(issue.fields.customfield_100.value, "Platform")
        self.assertEqual(len(issue.fields.issuelinks), 1)
        self.assertEqual(issue.fields.issuelinks[0].outwardIssue.key, "TEST-2")
        self.assertIsInstance(issue.changelog, SimpleNamespace)

    def test_convert_raw_issue_missing_key(self):
        with self.assertRaises(ValueError):
            convert_raw_issue_to_simple_object({"fields": {}})
