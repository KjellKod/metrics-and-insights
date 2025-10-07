#!/usr/bin/env python3
"""
Tests for epic_tracking.py module.

Following python-standards: prefer tests without mocks when possible.
Only mock external dependencies (get_ticket_points, get_completion_date).
"""

import unittest
import os
import sys
from datetime import datetime
from unittest.mock import patch

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from epic_tracking import bucket_counts_and_points_with_periods


class SimpleNamespace:
    """Simple object to hold attributes dynamically."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def create_mock_ticket(key, status, points=0):
    """Create a mock ticket object with minimal required structure."""
    ticket = SimpleNamespace()
    ticket.key = key
    ticket.fields = SimpleNamespace()
    ticket.fields.status = SimpleNamespace()
    ticket.fields.status.name = status
    # Store points for easy lookup in mock
    ticket._test_points = points
    return ticket


class TestBucketCountsAndPointsWithPeriods(unittest.TestCase):
    """Test the bucket_counts_and_points_with_periods function."""

    def setUp(self):
        """Set up test environment variables."""
        # Set test configuration for statuses
        os.environ["COMPLETION_STATUSES"] = "done,released"
        os.environ["EXCLUDED_STATUSES"] = "closed"

        # Clear the caches so our test env vars are picked up
        import jira_utils

        jira_utils._COMPLETION_STATUSES_CACHE = None
        jira_utils._EXCLUDED_STATUSES_CACHE = None

    def tearDown(self):
        """Clean up environment variables."""
        if "COMPLETION_STATUSES" in os.environ:
            del os.environ["COMPLETION_STATUSES"]
        if "EXCLUDED_STATUSES" in os.environ:
            del os.environ["EXCLUDED_STATUSES"]

    @patch("epic_tracking.get_completion_date")
    @patch("epic_tracking.get_ticket_points")
    def test_basic_bucketing(self, mock_get_points, mock_get_date):
        """Test basic ticket bucketing into done/open/excluded."""
        # Setup mocks
        mock_get_points.side_effect = lambda ticket: ticket._test_points
        mock_get_date.return_value = None  # No time period tracking for this test

        # Create test tickets
        children = [
            create_mock_ticket("PROJ-1", "Done", points=5),
            create_mock_ticket("PROJ-2", "Released", points=3),
            create_mock_ticket("PROJ-3", "In Progress", points=8),
            create_mock_ticket("PROJ-4", "To Do", points=2),
            create_mock_ticket("PROJ-5", "Closed", points=1),
        ]

        # Create empty time periods
        time_periods = []

        # Execute
        result = bucket_counts_and_points_with_periods(children, time_periods)

        # Unpack results
        (
            total_tickets,
            done_tickets,
            open_tickets,
            excluded_tickets,
            tickets_pct_done,
            total_points,
            done_points,
            open_points,
            excluded_points,
            points_pct_done,
            period_data,
        ) = result

        # Assertions
        self.assertEqual(total_tickets, 5)
        self.assertEqual(done_tickets, 2)  # Done + Released
        self.assertEqual(open_tickets, 2)  # In Progress + To Do
        self.assertEqual(excluded_tickets, 1)  # Closed

        self.assertEqual(total_points, 19)
        self.assertEqual(done_points, 8)  # 5 + 3
        self.assertEqual(open_points, 10)  # 8 + 2
        self.assertEqual(excluded_points, 1)  # 1

        # Percentages should exclude the excluded tickets
        # done / (total - excluded) = 2 / 4 = 50%
        self.assertEqual(tickets_pct_done, 50.0)
        # done_points / (total_points - excluded_points) = 8 / 18 = 44.4%
        self.assertEqual(points_pct_done, 44.4)

    @patch("epic_tracking.get_completion_date")
    @patch("epic_tracking.get_ticket_points")
    def test_case_insensitive_status(self, mock_get_points, mock_get_date):
        """Test that status matching is case-insensitive."""
        mock_get_points.side_effect = lambda ticket: ticket._test_points
        mock_get_date.return_value = None

        children = [
            create_mock_ticket("PROJ-1", "DONE", points=5),
            create_mock_ticket("PROJ-2", "done", points=3),
            create_mock_ticket("PROJ-3", "Done", points=2),
            create_mock_ticket("PROJ-4", "CLOSED", points=1),
        ]

        time_periods = []
        result = bucket_counts_and_points_with_periods(children, time_periods)

        done_tickets = result[1]
        excluded_tickets = result[3]

        self.assertEqual(done_tickets, 3)  # All three "done" variants
        self.assertEqual(excluded_tickets, 1)  # CLOSED

    @patch("epic_tracking.get_completion_date")
    @patch("epic_tracking.get_ticket_points")
    def test_time_period_tracking(self, mock_get_points, mock_get_date):
        """Test that completed tickets are tracked in the correct time period."""
        mock_get_points.side_effect = lambda ticket: ticket._test_points

        # Mock completion dates
        q1_date = datetime(2024, 2, 15)
        q2_date = datetime(2024, 5, 20)

        def get_completion_date_mock(ticket):
            if ticket.key == "PROJ-1":
                return q1_date
            elif ticket.key == "PROJ-2":
                return q2_date
            return None

        mock_get_date.side_effect = get_completion_date_mock

        children = [
            create_mock_ticket("PROJ-1", "Done", points=5),
            create_mock_ticket("PROJ-2", "Done", points=8),
            create_mock_ticket("PROJ-3", "In Progress", points=3),
        ]

        time_periods = [
            {"label": "2024-Q1", "start": datetime(2024, 1, 1), "end": datetime(2024, 3, 31)},
            {"label": "2024-Q2", "start": datetime(2024, 4, 1), "end": datetime(2024, 6, 30)},
        ]

        result = bucket_counts_and_points_with_periods(children, time_periods)
        period_data = result[10]

        # Check Q1 data
        self.assertEqual(period_data["2024-Q1"]["tickets_completed"], 1)
        self.assertEqual(period_data["2024-Q1"]["points_completed"], 5)

        # Check Q2 data
        self.assertEqual(period_data["2024-Q2"]["tickets_completed"], 1)
        self.assertEqual(period_data["2024-Q2"]["points_completed"], 8)

    @patch("epic_tracking.get_completion_date")
    @patch("epic_tracking.get_ticket_points")
    def test_zero_active_tickets(self, mock_get_points, mock_get_date):
        """Test that we handle division by zero when all tickets are excluded."""
        mock_get_points.side_effect = lambda ticket: ticket._test_points
        mock_get_date.return_value = None

        children = [
            create_mock_ticket("PROJ-1", "Closed", points=5),
            create_mock_ticket("PROJ-2", "Closed", points=3),
        ]

        time_periods = []
        result = bucket_counts_and_points_with_periods(children, time_periods)

        tickets_pct_done = result[4]
        points_pct_done = result[9]

        # Should return 0.0 instead of raising division by zero
        self.assertEqual(tickets_pct_done, 0.0)
        self.assertEqual(points_pct_done, 0.0)


if __name__ == "__main__":
    unittest.main()
