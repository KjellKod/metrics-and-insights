import unittest
import sys
import os
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta
import pytz
from jira.resources import Issue
"""
python3 -m unittest discover -v -s tests -p test_cycle_time.py
"""


# Add the parent directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from cycle_time import process_changelog, calculate_cycle_time_seconds

# Define the PST timezone
PST = timezone(timedelta(hours=-8))


class TestProcessChangelog(unittest.TestCase):

    def setUp(self):
        self.pst = pytz.timezone('America/Los_Angeles')
        self.start_date = self.pst.localize(datetime.strptime("2023-01-01", "%Y-%m-%d"))

    def create_mock_issue(self, changelog_entries):
        issue = MagicMock(spec=Issue)
        changelog = MagicMock()
        changelog.histories = changelog_entries
        issue.changelog = changelog
        return issue

    def create_changelog_entry(self, author, created, from_status, to_status):
        history = MagicMock()
        history.author = author
        history.created = created
        item = MagicMock()
        item.field = "status"
        item.fromString = from_status
        item.toString = to_status
        history.items = [item]
        return history

    def test_valid_changelog_with_code_review_and_released(self):
        changelog_entries = [
            self.create_changelog_entry("user1", "2023-01-02T10:00:00.000-0800", "open", "code review"),
            self.create_changelog_entry("user2", "2023-01-03T15:00:00.000-0800", "code review", "released")
        ]
        issue = self.create_mock_issue(changelog_entries)
        code_review_timestamp, released_timestamp = process_changelog(issue.changelog, self.start_date)

        self.assertIsNotNone(code_review_timestamp)
        self.assertIsNotNone(released_timestamp)

    def test_changelog_without_code_review(self):
        changelog_entries = [
            self.create_changelog_entry("user1", "2023-01-02T10:00:00.000-0800", "open", "in progress"),
            self.create_changelog_entry("user2", "2023-01-03T15:00:00.000-0800", "in progress", "released")
        ]
        issue = self.create_mock_issue(changelog_entries)
        code_review_timestamp, released_timestamp = process_changelog(issue.changelog, self.start_date)

        self.assertIsNone(code_review_timestamp)
        self.assertIsNotNone(released_timestamp)

    def test_changelog_without_released(self):
        changelog_entries = [
            self.create_changelog_entry("user1", "2023-01-02T10:00:00.000-0800", "open", "code review"),
            self.create_changelog_entry("user2", "2023-01-03T15:00:00.000-0800", "code review", "in progress")
        ]
        issue = self.create_mock_issue(changelog_entries)
        code_review_timestamp, released_timestamp = process_changelog(issue.changelog, self.start_date)

        self.assertIsNotNone(code_review_timestamp)
        self.assertIsNone(released_timestamp)

    def test_changelog_with_bulk_migration(self):
        changelog_entries = [
            self.create_changelog_entry("user1", "2022-12-31T10:00:00.000-0800", "open", "code review"),
            self.create_changelog_entry("user2", "2022-12-31T15:00:00.000-0800", "code review", "released")
        ]
        expected_code_review_timestamp = datetime.strptime("2022-12-31T10:00:00.000-0800", "%Y-%m-%dT%H:%M:%S.%f%z")
        expected_released_timestamp = datetime.strptime("2022-12-31T15:00:00.000-0800", "%Y-%m-%dT%H:%M:%S.%f%z")
        issue = self.create_mock_issue(changelog_entries)
        code_review_timestamp, released_timestamp = process_changelog(issue.changelog, self.start_date)

        # bulk migration check, we don't want to have jira data logic depending on the "update status"
        # we want to use the actual history created time stamp. Here we should ignore the ticket since the migration
        # happened after the time we are looking at
        self.assertIsNone(code_review_timestamp)
        self.assertIsNone(released_timestamp)
        self.assertNotEqual(code_review_timestamp, expected_code_review_timestamp)
        self.assertNotEqual(released_timestamp, expected_released_timestamp)

    def test_empty_changelog(self):
        changelog_entries = []
        issue = self.create_mock_issue(changelog_entries)
        code_review_timestamp, released_timestamp = process_changelog(issue.changelog, self.start_date)

        self.assertIsNone(code_review_timestamp)
        self.assertIsNone(released_timestamp)

    def test_changelog_with_multiple_code_review_and_released(self):
        changelog_entries = [
            self.create_changelog_entry("user1", "2023-01-02T10:00:00.000-0800", "open", "code review"),
            self.create_changelog_entry("user2", "2023-01-03T15:00:00.000-0800", "code review", "in progress"),
            self.create_changelog_entry("user3", "2023-01-04T10:00:00.000-0800", "in progress", "code review"),
            self.create_changelog_entry("user4", "2023-01-05T15:00:00.000-0800", "code review", "released")
        ]
        issue = self.create_mock_issue(changelog_entries)
        code_review_timestamp, released_timestamp = process_changelog(issue.changelog, self.start_date)

        expected_code_review_timestamp = datetime.strptime("2023-01-02T10:00:00.000-0800", "%Y-%m-%dT%H:%M:%S.%f%z")
        expected_released_timestamp = datetime.strptime("2023-01-05T15:00:00.000-0800", "%Y-%m-%dT%H:%M:%S.%f%z")

        self.assertIsNotNone(code_review_timestamp)
        self.assertIsNotNone(released_timestamp)
        self.assertEqual(code_review_timestamp, expected_code_review_timestamp)
        self.assertEqual(released_timestamp, expected_released_timestamp)

class TestCalculateCycleTimeSeconds(unittest.TestCase):
    @patch('cycle_time.validate_issue')
    @patch('cycle_time.localize_start_date')
    @patch('cycle_time.process_changelog')
    @patch('cycle_time.log_process_process_changelog')
    @patch('cycle_time.calculate_business_time')
    @patch('cycle_time.log_cycle_time')
    def test_calculate_cycle_time_seconds(self, mock_log_cycle_time, mock_calculate_business_time, mock_log_process_process_changelog, mock_process_changelog, mock_localize_start_date, mock_validate_issue):
        # Mocking the dependencies
        mock_validate_issue.return_value = True
        mock_localize_start_date.return_value = datetime(2022, 12, 31, 10, 0, tzinfo=PST)
        mock_process_changelog.return_value = (
            datetime(2022, 12, 31, 10, 0, tzinfo=PST),
            datetime(2022, 12, 31, 15, 0, tzinfo=PST)
        )
        mock_log_process_process_changelog.return_value = "Log string"
        mock_calculate_business_time.return_value = (18000, 2.5)  # 5 hours in seconds, 2.5 business days
        mock_log_cycle_time.return_value = "Updated log string"

        # Creating a mock issue
        mock_issue = MagicMock()
        mock_issue.key = "ISSUE-123"
        mock_issue.changelog = []

        # Calling the function under test
        business_seconds, month_key = calculate_cycle_time_seconds("2022-12-31T10:00:00.000-0800", mock_issue)

        # Asserting the results
        self.assertEqual(business_seconds, 18000)
        self.assertEqual(month_key, "2022-12")

        # Asserting the mocks were called with expected arguments
        mock_validate_issue.assert_called_once_with(mock_issue)
        mock_localize_start_date.assert_called_once_with("2022-12-31T10:00:00.000-0800")
        mock_process_changelog.assert_called_once_with(mock_issue.changelog, mock_localize_start_date.return_value)
        mock_log_process_process_changelog.assert_called_once_with(mock_issue.changelog)
        mock_calculate_business_time.assert_called_once_with(
            datetime(2022, 12, 31, 10, 0, tzinfo=PST),
            datetime(2022, 12, 31, 15, 0, tzinfo=PST)
        )
        mock_log_cycle_time.assert_called_once_with(
            "ISSUE-123",
            "Log string",
            18000,
            2.5,
            datetime(2022, 12, 31, 10, 0, tzinfo=PST),
            datetime(2022, 12, 31, 15, 0, tzinfo=PST)
        )










if __name__ == "__main__":
    unittest.main()
