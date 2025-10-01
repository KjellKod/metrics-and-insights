import sys
import os
import unittest
from datetime import datetime, timezone, timedelta

# Add the parent directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Import functions to test
# pylint: disable=wrong-import-position,import-error
from epic_tracking import get_quarter_dates, get_month_dates, generate_time_periods, build_epic_jql


class TestQuarterDates(unittest.TestCase):
    """Test quarter date calculation functions."""

    def test_q1_dates(self):
        """Test Q1 date boundaries."""
        start, end = get_quarter_dates(2024, 1)

        expected_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        expected_end = datetime(2024, 3, 31, 23, 59, 59, tzinfo=timezone.utc)

        self.assertEqual(start, expected_start)
        self.assertEqual(end, expected_end)

    def test_q2_dates(self):
        """Test Q2 date boundaries."""
        start, end = get_quarter_dates(2024, 2)

        expected_start = datetime(2024, 4, 1, tzinfo=timezone.utc)
        expected_end = datetime(2024, 6, 30, 23, 59, 59, tzinfo=timezone.utc)

        self.assertEqual(start, expected_start)
        self.assertEqual(end, expected_end)

    def test_q3_dates(self):
        """Test Q3 date boundaries."""
        start, end = get_quarter_dates(2024, 3)

        expected_start = datetime(2024, 7, 1, tzinfo=timezone.utc)
        expected_end = datetime(2024, 9, 30, 23, 59, 59, tzinfo=timezone.utc)

        self.assertEqual(start, expected_start)
        self.assertEqual(end, expected_end)

    def test_q4_dates(self):
        """Test Q4 date boundaries."""
        start, end = get_quarter_dates(2024, 4)

        expected_start = datetime(2024, 10, 1, tzinfo=timezone.utc)
        expected_end = datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

        self.assertEqual(start, expected_start)
        self.assertEqual(end, expected_end)

    def test_leap_year_q1(self):
        """Test Q1 in a leap year (should not affect Q1)."""
        start, end = get_quarter_dates(2024, 1)  # 2024 is a leap year

        expected_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        expected_end = datetime(2024, 3, 31, 23, 59, 59, tzinfo=timezone.utc)

        self.assertEqual(start, expected_start)
        self.assertEqual(end, expected_end)


class TestMonthDates(unittest.TestCase):
    """Test month date calculation functions."""

    def test_january_dates(self):
        """Test January date boundaries."""
        start, end = get_month_dates(2024, 1)

        expected_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        expected_end = datetime(2024, 1, 31, 23, 59, 59, tzinfo=timezone.utc)

        self.assertEqual(start, expected_start)
        self.assertEqual(end, expected_end)

    def test_february_leap_year(self):
        """Test February in a leap year."""
        start, end = get_month_dates(2024, 2)  # 2024 is a leap year

        expected_start = datetime(2024, 2, 1, tzinfo=timezone.utc)
        expected_end = datetime(2024, 2, 29, 23, 59, 59, tzinfo=timezone.utc)

        self.assertEqual(start, expected_start)
        self.assertEqual(end, expected_end)

    def test_february_non_leap_year(self):
        """Test February in a non-leap year."""
        start, end = get_month_dates(2023, 2)  # 2023 is not a leap year

        expected_start = datetime(2023, 2, 1, tzinfo=timezone.utc)
        expected_end = datetime(2023, 2, 28, 23, 59, 59, tzinfo=timezone.utc)

        self.assertEqual(start, expected_start)
        self.assertEqual(end, expected_end)

    def test_december_dates(self):
        """Test December date boundaries (year rollover case)."""
        start, end = get_month_dates(2024, 12)

        expected_start = datetime(2024, 12, 1, tzinfo=timezone.utc)
        expected_end = datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

        self.assertEqual(start, expected_start)
        self.assertEqual(end, expected_end)

    def test_april_dates(self):
        """Test April (30-day month)."""
        start, end = get_month_dates(2024, 4)

        expected_start = datetime(2024, 4, 1, tzinfo=timezone.utc)
        expected_end = datetime(2024, 4, 30, 23, 59, 59, tzinfo=timezone.utc)

        self.assertEqual(start, expected_start)
        self.assertEqual(end, expected_end)


class TestGenerateTimePeriods(unittest.TestCase):
    """Test time period generation logic."""

    def test_single_quarter(self):
        """Test generating a single quarter period."""
        time_period = {"type": "quarter", "year": 2024, "quarter": 3, "periods": 1}

        periods = generate_time_periods(time_period)

        self.assertEqual(len(periods), 1)
        self.assertEqual(periods[0]["label"], "2024-Q3")
        self.assertEqual(periods[0]["type"], "quarter")

        # Check dates
        expected_start = datetime(2024, 7, 1, tzinfo=timezone.utc)
        expected_end = datetime(2024, 9, 30, 23, 59, 59, tzinfo=timezone.utc)
        self.assertEqual(periods[0]["start"], expected_start)
        self.assertEqual(periods[0]["end"], expected_end)

    def test_multiple_quarters_same_year(self):
        """Test generating multiple quarters within the same year."""
        time_period = {"type": "quarter", "year": 2024, "quarter": 4, "periods": 3}

        periods = generate_time_periods(time_period)

        self.assertEqual(len(periods), 3)

        # Should go backwards: Q4, Q3, Q2
        expected_labels = ["2024-Q4", "2024-Q3", "2024-Q2"]
        actual_labels = [p["label"] for p in periods]
        self.assertEqual(actual_labels, expected_labels)

    def test_quarters_with_year_rollover(self):
        """Test generating quarters that cross year boundaries."""
        time_period = {"type": "quarter", "year": 2024, "quarter": 2, "periods": 4}

        periods = generate_time_periods(time_period)

        self.assertEqual(len(periods), 4)

        # Should go backwards: 2024-Q2, 2024-Q1, 2023-Q4, 2023-Q3
        expected_labels = ["2024-Q2", "2024-Q1", "2023-Q4", "2023-Q3"]
        actual_labels = [p["label"] for p in periods]
        self.assertEqual(actual_labels, expected_labels)

    def test_single_month(self):
        """Test generating a single month period."""
        time_period = {"type": "month", "year": 2024, "month": 6, "periods": 1}

        periods = generate_time_periods(time_period)

        self.assertEqual(len(periods), 1)
        self.assertEqual(periods[0]["label"], "2024-06")
        self.assertEqual(periods[0]["type"], "month")

    def test_months_with_year_rollover(self):
        """Test generating months that cross year boundaries."""
        time_period = {"type": "month", "year": 2024, "month": 2, "periods": 4}

        periods = generate_time_periods(time_period)

        self.assertEqual(len(periods), 4)

        # Should go backwards: 2024-02, 2024-01, 2023-12, 2023-11
        expected_labels = ["2024-02", "2024-01", "2023-12", "2023-11"]
        actual_labels = [p["label"] for p in periods]
        self.assertEqual(actual_labels, expected_labels)

    def test_year_period(self):
        """Test generating a year period."""
        time_period = {"type": "year", "year": 2024, "periods": 1}

        periods = generate_time_periods(time_period)

        self.assertEqual(len(periods), 1)
        self.assertEqual(periods[0]["label"], "2024")
        self.assertEqual(periods[0]["type"], "year")

        # Check dates span full year
        expected_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        expected_end = datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
        self.assertEqual(periods[0]["start"], expected_start)
        self.assertEqual(periods[0]["end"], expected_end)


class TestBuildEpicJql(unittest.TestCase):
    """Test JQL building logic."""

    def test_single_epic(self):
        """Test JQL for single epic."""
        from unittest.mock import MagicMock

        args = MagicMock()
        args.epic = "PROJ-123"
        args.epics = None
        args.label = None
        args.labels = None

        jql = build_epic_jql(args)
        self.assertEqual(jql, "key = PROJ-123")

    def test_multiple_epics(self):
        """Test JQL for multiple epics."""
        from unittest.mock import MagicMock

        args = MagicMock()
        args.epic = None
        args.epics = "PROJ-123,PROJ-456,PROJ-789"
        args.label = None
        args.labels = None

        jql = build_epic_jql(args)
        self.assertEqual(jql, "key in (PROJ-123, PROJ-456, PROJ-789)")

    def test_multiple_epics_with_spaces(self):
        """Test JQL for multiple epics with extra spaces."""
        from unittest.mock import MagicMock

        args = MagicMock()
        args.epic = None
        args.epics = " PROJ-123 , PROJ-456 , PROJ-789 "
        args.label = None
        args.labels = None

        jql = build_epic_jql(args)
        self.assertEqual(jql, "key in (PROJ-123, PROJ-456, PROJ-789)")

    def test_single_label(self):
        """Test JQL for single label."""
        from unittest.mock import MagicMock

        args = MagicMock()
        args.epic = None
        args.epics = None
        args.label = "2024-Q1"
        args.labels = None

        jql = build_epic_jql(args)
        self.assertEqual(jql, 'issuetype = Epic AND labels = "2024-Q1"')

    def test_multiple_labels(self):
        """Test JQL for multiple labels."""
        from unittest.mock import MagicMock

        args = MagicMock()
        args.epic = None
        args.epics = None
        args.label = None
        args.labels = "2024-Q1,feature,urgent"

        jql = build_epic_jql(args)
        self.assertEqual(jql, 'issuetype = Epic AND labels IN ("2024-Q1", "feature", "urgent")')

    def test_multiple_labels_with_spaces(self):
        """Test JQL for multiple labels with extra spaces."""
        from unittest.mock import MagicMock

        args = MagicMock()
        args.epic = None
        args.epics = None
        args.label = None
        args.labels = " 2024-Q1 , feature , urgent "

        jql = build_epic_jql(args)
        self.assertEqual(jql, 'issuetype = Epic AND labels IN ("2024-Q1", "feature", "urgent")')


if __name__ == "__main__":
    unittest.main()
