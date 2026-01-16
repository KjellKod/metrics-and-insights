import argparse
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytz
from jira.resources import Issue

# Add the parent directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
# pylint: disable=wrong-import-position,import-error
from cycle_time import (
    business_time_spent_in_seconds,
    calculate_monthly_cycle_time,
    parse_month,
    process_changelog,
)

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
            self.create_changelog_entry("user2", "2023-01-03T15:00:00.000-0800", "code review", "released"),
            self.create_changelog_entry("user1", "2023-01-02T10:00:00.000-0800", "open", "code review"),
        ]
        issue = self.create_mock_issue(changelog_entries)
        code_review_timestamp, released_timestamp = process_changelog(issue)

        self.assertIsNotNone(code_review_timestamp)
        self.assertIsNotNone(released_timestamp)

    def test_changelog_without_code_review(self):
        changelog_entries = [
            self.create_changelog_entry("user2", "2023-01-03T15:00:00.000-0800", "in progress", "released"),
            self.create_changelog_entry("user1", "2023-01-02T10:00:00.000-0800", "open", "in progress"),
        ]
        issue = self.create_mock_issue(changelog_entries)
        code_review_timestamp, released_timestamp = process_changelog(issue)

        self.assertIsNone(code_review_timestamp)
        self.assertIsNotNone(released_timestamp)

    def test_changelog_without_released(self):
        changelog_entries = [
            self.create_changelog_entry("user2", "2023-01-03T15:00:00.000-0800", "code review", "in progress"),
            self.create_changelog_entry("user1", "2023-01-02T10:00:00.000-0800", "open", "code review"),
        ]
        issue = self.create_mock_issue(changelog_entries)
        code_review_timestamp, released_timestamp = process_changelog(issue)

        self.assertIsNotNone(code_review_timestamp)
        self.assertIsNone(released_timestamp)

    def test_empty_changelog(self):
        changelog_entries = []
        issue = self.create_mock_issue(changelog_entries)
        code_review_timestamp, released_timestamp = process_changelog(issue)

        self.assertIsNone(code_review_timestamp)
        self.assertIsNone(released_timestamp)

    def test_changelog_with_multiple_code_review_and_released(self):
        changelog_entries = [
            self.create_changelog_entry("user4", "2024-01-05T15:00:00.000-0800", "code review", "released"),
            self.create_changelog_entry("user3", "2023-01-04T10:00:00.000-0800", "in progress", "code review"),
            self.create_changelog_entry("user2", "2022-01-03T15:00:00.000-0800", "code review", "in progress"),
            self.create_changelog_entry("user1", "2021-01-02T10:00:00.000-0800", "open", "code review"),
        ]
        issue = self.create_mock_issue(changelog_entries)
        code_review_timestamp, released_timestamp = process_changelog(issue)
        self.assertIsNotNone(code_review_timestamp)
        self.assertIsNotNone(released_timestamp)
        expected_code_review_timestamp = datetime.strptime("2021-01-02T10:00:00.000-0800", "%Y-%m-%dT%H:%M:%S.%f%z")
        expected_released_timestamp = datetime.strptime("2024-01-05T15:00:00.000-0800", "%Y-%m-%dT%H:%M:%S.%f%z")
        self.assertEqual(code_review_timestamp, expected_code_review_timestamp)
        self.assertEqual(released_timestamp, expected_released_timestamp)

    def test_changelog_with_multiple_releases(self):
        changelog_entries = [
            self.create_changelog_entry("user4", "2024-01-05T15:00:00.000-0800", "reverted", "released"),
            self.create_changelog_entry("user3", "2023-01-04T10:00:00.000-0800", "released", "reverted"),
            self.create_changelog_entry("user2", "2022-01-03T15:00:00.000-0800", "code review", "released"),
            self.create_changelog_entry("user1", "2021-01-02T10:00:00.000-0800", "open", "code review"),
        ]
        issue = self.create_mock_issue(changelog_entries)
        code_review_timestamp, released_timestamp = process_changelog(issue)
        self.assertIsNotNone(code_review_timestamp)
        self.assertIsNotNone(released_timestamp)
        expected_code_review_timestamp = datetime.strptime("2021-01-02T10:00:00.000-0800", "%Y-%m-%dT%H:%M:%S.%f%z")
        expected_released_timestamp = datetime.strptime("2024-01-05T15:00:00.000-0800", "%Y-%m-%dT%H:%M:%S.%f%z")
        self.assertEqual(code_review_timestamp, expected_code_review_timestamp)
        self.assertEqual(released_timestamp, expected_released_timestamp)


class TestBusinessTimeCalculations(unittest.TestCase):
    """Tests for business_time_spent_in_seconds function.

    This function calculates time spent during business hours (8 hours per weekday).
    Key behaviors:
    - Only counts Monday-Friday
    - Caps at 8 hours (28800 seconds) per day
    - Handles multi-day spans
    - Excludes weekends
    """

    def test_same_day_within_8_hours(self):
        """Test calculation for same day, within 8 hour cap."""
        # Monday Jan 2, 2023: 9am to 1pm = 4 hours
        start = datetime(2023, 1, 2, 9, 0)  # Monday
        end = datetime(2023, 1, 2, 13, 0)
        result = business_time_spent_in_seconds(start, end)
        expected = 4 * 3600  # 4 hours
        self.assertEqual(result, expected, f"Expected {expected}, got {result}")

    def test_same_day_exceeds_8_hours(self):
        """Test that same day duration is capped at 8 hours."""
        # Monday Jan 2, 2023: 9am to 11pm = should cap at 8 hours
        start = datetime(2023, 1, 2, 9, 0)  # Monday
        end = datetime(2023, 1, 2, 23, 0)
        result = business_time_spent_in_seconds(start, end)
        expected = 8 * 3600  # 8 hours (capped)
        self.assertEqual(result, expected, f"Expected {expected}, got {result}")

    def test_two_consecutive_weekdays(self):
        """Test calculation spanning two consecutive weekdays."""
        # Monday Jan 2, 2023 2pm to Tuesday Jan 3, 2023 10am
        # Monday: 2pm to end of day = min(10 hours, 8) = 8 hours
        # Tuesday: start to 10am = min(10 hours, 8) = 8 hours
        # Total = 16 hours
        start = datetime(2023, 1, 2, 14, 0)  # Monday 2pm
        end = datetime(2023, 1, 3, 10, 0)  # Tuesday 10am
        result = business_time_spent_in_seconds(start, end)
        expected = 16 * 3600  # 16 hours
        self.assertEqual(result, expected, f"Expected {expected}, got {result}")

    def test_spans_weekend(self):
        """Test that weekends are excluded from calculation."""
        # Friday Jan 6, 2023 2pm to Monday Jan 9, 2023 10am
        # Friday: 2pm to end of day = min(10 hours, 8) = 8 hours
        # Saturday: 0 hours (weekend)
        # Sunday: 0 hours (weekend)
        # Monday: start to 10am = min(10 hours, 8) = 8 hours
        # Total = 16 hours
        start = datetime(2023, 1, 6, 14, 0)  # Friday 2pm
        end = datetime(2023, 1, 9, 10, 0)  # Monday 10am
        result = business_time_spent_in_seconds(start, end)
        expected = 16 * 3600  # 16 hours
        self.assertEqual(result, expected, f"Expected {expected}, got {result}")

    def test_starts_on_saturday(self):
        """Test that starting on Saturday only counts from Monday."""
        # Saturday Jan 7, 2023 9am to Monday Jan 9, 2023 5pm
        # Saturday: 0 hours (weekend)
        # Sunday: 0 hours (weekend)
        # Monday: start to 5pm = min(8 hours, 8) = 8 hours
        start = datetime(2023, 1, 7, 9, 0)  # Saturday
        end = datetime(2023, 1, 9, 17, 0)  # Monday
        result = business_time_spent_in_seconds(start, end)
        expected = 8 * 3600  # 8 hours
        self.assertEqual(result, expected, f"Expected {expected}, got {result}")

    def test_starts_on_sunday(self):
        """Test that starting on Sunday only counts from Monday at midnight."""
        # Sunday Jan 8, 2023 9am to Monday Jan 9, 2023 2pm
        # Sunday: 0 hours (weekend, skipped)
        # Monday: midnight to 2pm = 14 hours, capped at 8 hours = 8 hours
        start = datetime(2023, 1, 8, 9, 0)  # Sunday
        end = datetime(2023, 1, 9, 14, 0)  # Monday
        result = business_time_spent_in_seconds(start, end)
        expected = 8 * 3600  # 8 hours (capped)
        self.assertEqual(result, expected, f"Expected {expected}, got {result}")

    def test_entire_weekend(self):
        """Test that an entire weekend returns 0 hours."""
        # Saturday Jan 7, 2023 9am to Sunday Jan 8, 2023 5pm
        start = datetime(2023, 1, 7, 9, 0)  # Saturday
        end = datetime(2023, 1, 8, 17, 0)  # Sunday
        result = business_time_spent_in_seconds(start, end)
        expected = 0  # No business hours on weekend
        self.assertEqual(result, expected, f"Expected {expected}, got {result}")

    def test_full_work_week(self):
        """Test calculation for a full work week."""
        # Monday Jan 2, 2023 9am to Friday Jan 6, 2023 5pm
        # Each day capped at 8 hours = 5 days * 8 hours = 40 hours
        start = datetime(2023, 1, 2, 9, 0)  # Monday
        end = datetime(2023, 1, 6, 17, 0)  # Friday
        result = business_time_spent_in_seconds(start, end)
        expected = 40 * 3600  # 40 hours
        self.assertEqual(result, expected, f"Expected {expected}, got {result}")

    def test_two_full_weeks(self):
        """Test calculation spanning two weeks with weekends."""
        # Monday Jan 2, 2023 to Friday Jan 13, 2023
        # Week 1: Mon-Fri = 40 hours
        # Weekend: 0 hours
        # Week 2: Mon-Fri = 40 hours
        # Total = 80 hours
        start = datetime(2023, 1, 2, 9, 0)  # Monday
        end = datetime(2023, 1, 13, 17, 0)  # Friday (next week)
        result = business_time_spent_in_seconds(start, end)
        expected = 80 * 3600  # 80 hours
        self.assertEqual(result, expected, f"Expected {expected}, got {result}")

    def test_very_short_duration(self):
        """Test calculation for very short duration (less than 1 hour)."""
        # Monday Jan 2, 2023: 9am to 9:30am = 30 minutes
        start = datetime(2023, 1, 2, 9, 0)  # Monday
        end = datetime(2023, 1, 2, 9, 30)
        result = business_time_spent_in_seconds(start, end)
        expected = 30 * 60  # 30 minutes
        self.assertEqual(result, expected, f"Expected {expected}, got {result}")

    def test_start_equals_end(self):
        """Test that same start and end time returns 0."""
        # Monday Jan 2, 2023: 9am to 9am
        start = datetime(2023, 1, 2, 9, 0)  # Monday
        end = datetime(2023, 1, 2, 9, 0)
        result = business_time_spent_in_seconds(start, end)
        expected = 0
        self.assertEqual(result, expected, f"Expected {expected}, got {result}")

    def test_end_of_day_boundary(self):
        """Test calculation ending at day boundary."""
        # Monday Jan 2, 2023: 9am to 11:59pm = should cap at 8 hours
        start = datetime(2023, 1, 2, 9, 0)  # Monday
        end = datetime(2023, 1, 2, 23, 59)
        result = business_time_spent_in_seconds(start, end)
        expected = 8 * 3600  # 8 hours (capped)
        self.assertEqual(result, expected, f"Expected {expected}, got {result}")

    def test_partial_first_day_full_second_day(self):
        """Test with partial first day and full second day."""
        # Monday Jan 2, 2023 2pm to Tuesday Jan 3, 2023 11pm
        # Monday: 2pm to end of day = min(10 hours, 8) = 8 hours
        # Tuesday: all day = 8 hours
        # Total = 16 hours
        start = datetime(2023, 1, 2, 14, 0)  # Monday 2pm
        end = datetime(2023, 1, 3, 23, 0)  # Tuesday 11pm
        result = business_time_spent_in_seconds(start, end)
        expected = 16 * 3600  # 16 hours
        self.assertEqual(result, expected, f"Expected {expected}, got {result}")

    def test_three_weekdays_in_a_row(self):
        """Test calculation spanning three consecutive weekdays."""
        # Monday Jan 2 3pm to Wednesday Jan 4 1pm
        # Monday: 3pm to end = min(9 hours, 8) = 8 hours
        # Tuesday: full day = 8 hours
        # Wednesday: start to 1pm = min(1pm, 8) = 8 hours
        # Total = 24 hours
        start = datetime(2023, 1, 2, 15, 0)  # Monday 3pm
        end = datetime(2023, 1, 4, 13, 0)  # Wednesday 1pm
        result = business_time_spent_in_seconds(start, end)
        expected = 24 * 3600  # 24 hours
        self.assertEqual(result, expected, f"Expected {expected}, got {result}")


class TestParseMonth(unittest.TestCase):
    def test_valid_month(self):
        self.assertEqual(parse_month("1"), 1)
        self.assertEqual(parse_month("12"), 12)

    def test_invalid_month(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_month("0")
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_month("13")
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_month("not-a-month")


class TestAssigneeCycleTimeAggregation(unittest.TestCase):
    def create_issue(self, key, assignee_name):
        issue = MagicMock()
        issue.key = key
        issue.fields.assignee.displayName = assignee_name
        return issue

    @patch("cycle_time.get_team")
    @patch("cycle_time.calculate_cycle_time_seconds")
    @patch("cycle_time.get_tickets_from_jira")
    def test_assignee_metrics_for_selected_month(
        self, mock_get_tickets, mock_calc_cycle_time, mock_get_team
    ):
        issue1 = self.create_issue("ISSUE-1", "Alice")
        issue2 = self.create_issue("ISSUE-2", "Bob")
        issue3 = self.create_issue("ISSUE-3", "Alice")

        mock_get_tickets.return_value = [issue1, issue2, issue3]
        mock_get_team.return_value = "alpha"
        mock_calc_cycle_time.side_effect = [
            (100, "2024-02", None),
            (200, "2024-02", None),
            (150, "2024-03", None),
        ]

        cycle_times, assignee_times = calculate_monthly_cycle_time(
            ["PROJ"], "2024-01-01", "2024-12-31", "2024-02"
        )

        self.assertIn("alpha", cycle_times)
        self.assertIn("all", cycle_times)
        self.assertIsNotNone(assignee_times)
        self.assertIn("alpha", assignee_times)

        team_assignees = assignee_times["alpha"]
        self.assertEqual(len(team_assignees["Alice"]), 1)
        self.assertEqual(len(team_assignees["Bob"]), 1)


if __name__ == "__main__":
    unittest.main()
