import unittest
import sys
import os
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta
import pytz

# Add the parent directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
# pylint: disable=wrong-import-position,import-error
from cycle_time import process_changelog, calculate_cycle_time_seconds

from jira.resources import Issue


# Define the PST timezone
PST = timezone(timedelta(hours=-8))


class TestProcessChangelog(unittest.TestCase):

    def setUp(self):
        self.pst = pytz.timezone("America/Los_Angeles")
        self.start_date = self.pst.localize(datetime.strptime("2023-01-01", "%Y-%m-%d"))

    def create_mock_issue(self, changelog_entries):
        issue = MagicMock(spec=Issue)
        changelog = MagicMock()
        changelog.histories = changelog_entries
        issue.changelog = changelog
        issue.key = "ISSUE-123"
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
            self.create_changelog_entry(
                "user2", "2023-01-03T15:00:00.000-0800", "code review", "released"
            ),
            self.create_changelog_entry(
                "user1", "2023-01-02T10:00:00.000-0800", "open", "code review"
            ),
        ]
        issue = self.create_mock_issue(changelog_entries)
        code_review_timestamp, released_timestamp = process_changelog(
            issue, self.start_date
        )

        self.assertIsNotNone(code_review_timestamp)
        self.assertIsNotNone(released_timestamp)

    def test_changelog_without_code_review(self):
        changelog_entries = [
            self.create_changelog_entry(
                "user2", "2023-01-03T15:00:00.000-0800", "in progress", "released"
            ),
            self.create_changelog_entry(
                "user1", "2023-01-02T10:00:00.000-0800", "open", "in progress"
            ),
        ]
        issue = self.create_mock_issue(changelog_entries)
        code_review_timestamp, released_timestamp = process_changelog(
            issue, self.start_date
        )

        self.assertIsNone(code_review_timestamp)
        self.assertIsNotNone(released_timestamp)

    def test_changelog_without_released(self):
        changelog_entries = [
            self.create_changelog_entry(
                "user2", "2023-01-03T15:00:00.000-0800", "code review", "in progress"
            ),
            self.create_changelog_entry(
                "user1", "2023-01-02T10:00:00.000-0800", "open", "code review"
            ),
        ]
        issue = self.create_mock_issue(changelog_entries)
        code_review_timestamp, released_timestamp = process_changelog(
            issue, self.start_date
        )

        self.assertIsNotNone(code_review_timestamp)
        self.assertIsNone(released_timestamp)

    def test_empty_changelog(self):
        changelog_entries = []
        issue = self.create_mock_issue(changelog_entries)
        code_review_timestamp, released_timestamp = process_changelog(
            issue, self.start_date
        )

        self.assertIsNone(code_review_timestamp)
        self.assertIsNone(released_timestamp)

    def test_changelog_with_multiple_code_review_and_released(self):
        changelog_entries = [
            self.create_changelog_entry(
                "user4", "2024-01-05T15:00:00.000-0800", "code review", "released"
            ),
            self.create_changelog_entry(
                "user3", "2023-01-04T10:00:00.000-0800", "in progress", "code review"
            ),
            self.create_changelog_entry(
                "user2", "2022-01-03T15:00:00.000-0800", "code review", "in progress"
            ),
            self.create_changelog_entry(
                "user1", "2021-01-02T10:00:00.000-0800", "open", "code review"
            ),
        ]
        issue = self.create_mock_issue(changelog_entries)
        code_review_timestamp, released_timestamp = process_changelog(
            issue, self.start_date
        )
        self.assertIsNotNone(code_review_timestamp)
        self.assertIsNotNone(released_timestamp)
        expected_code_review_timestamp = datetime.strptime(
            "2021-01-02T10:00:00.000-0800", "%Y-%m-%dT%H:%M:%S.%f%z"
        )
        expected_released_timestamp = datetime.strptime(
            "2024-01-05T15:00:00.000-0800", "%Y-%m-%dT%H:%M:%S.%f%z"
        )
        self.assertEqual(code_review_timestamp, expected_code_review_timestamp)
        self.assertEqual(released_timestamp, expected_released_timestamp)

    def test_changelog_with_multiple_releases(self):
        changelog_entries = [
            self.create_changelog_entry(
                "user4", "2024-01-05T15:00:00.000-0800", "reverted", "released"
            ),
            self.create_changelog_entry(
                "user3", "2023-01-04T10:00:00.000-0800", "released", "reverted"
            ),
            self.create_changelog_entry(
                "user2", "2022-01-03T15:00:00.000-0800", "code review", "released"
            ),
            self.create_changelog_entry(
                "user1", "2021-01-02T10:00:00.000-0800", "open", "code review"
            ),
        ]
        issue = self.create_mock_issue(changelog_entries)
        code_review_timestamp, released_timestamp = process_changelog(
            issue, self.start_date
        )
        self.assertIsNotNone(code_review_timestamp)
        self.assertIsNotNone(released_timestamp)
        expected_code_review_timestamp = datetime.strptime(
            "2021-01-02T10:00:00.000-0800", "%Y-%m-%dT%H:%M:%S.%f%z"
        )
        expected_released_timestamp = datetime.strptime(
            "2024-01-05T15:00:00.000-0800", "%Y-%m-%dT%H:%M:%S.%f%z"
        )
        self.assertEqual(code_review_timestamp, expected_code_review_timestamp)
        self.assertEqual(released_timestamp, expected_released_timestamp)


class TestCalculateCycleTimeSeconds(unittest.TestCase):
    @patch("cycle_time.validate_issue")
    @patch("cycle_time.localize_start_date")
    @patch("cycle_time.process_changelog")
    @patch("cycle_time.calculate_business_time")
    def test_calculate_cycle_time_seconds(
        self,
        mock_calculate_business_time,
        mock_process_changelog,
        mock_localize_start_date,
        mock_validate_issue,
    ):
        # Mocking the dependencies
        mock_validate_issue.return_value = True
        mock_localize_start_date.return_value = datetime(
            2022, 12, 31, 10, 0, tzinfo=PST
        )
        mock_process_changelog.return_value = (
            datetime(2022, 12, 31, 10, 0, tzinfo=PST),
            datetime(2022, 12, 31, 15, 0, tzinfo=PST),
        )
        mock_calculate_business_time.return_value = (
            18000,
            2.5,
        )  # 5 hours in seconds, 2.5 business days

        # Creating a mock issue
        mock_issue = MagicMock()
        mock_issue.key = "ISSUE-123"
        mock_issue.changelog = []

        # Calling the function under test
        business_seconds, month_key = calculate_cycle_time_seconds(
            "2022-12-31T10:00:00.000-0800", mock_issue
        )

        # Asserting the results
        self.assertEqual(business_seconds, 18000)
        self.assertEqual(month_key, "2022-12")


if __name__ == "__main__":
    unittest.main()
