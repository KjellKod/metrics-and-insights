import unittest 
from datetime import datetime
from jira_time_utils import get_week_intervals, business_time_spent_in_seconds

class TestBusinessTimeSpentInSeconds(unittest.TestCase):

    def test_within_single_business_day(self):
        start = datetime(2023, 4, 3, 9)  # Monday, April 3, 2023, 09:00 AM
        end = datetime(2023, 4, 3, 17)   # Monday, April 3, 2023, 05:00 PM
        self.assertEqual(business_time_spent_in_seconds(start, end), 8 * 60 * 60)

    def test_across_multiple_business_days(self):
        start = datetime(2023, 4, 3, 9)  # Monday, April 3, 2023, 09:00 AM
        end = datetime(2023, 4, 5, 17)   # Wednesday, April 5, 2023, 05:00 PM
        self.assertEqual(business_time_spent_in_seconds(start, end), 3 * 8 * 60 * 60)

    def test_including_weekend(self):
        start = datetime(2023, 4, 7, 9)  # Friday, April 7, 2023, 09:00 AM
        end = datetime(2023, 4, 10, 17)  # Monday, April 10, 2023, 05:00 PM
        self.assertEqual(business_time_spent_in_seconds(start, end), 2 * 8 * 60 * 60)

    def test_start_and_end_outside_business_hours(self):
        start = datetime(2023, 4, 3, 7)  # Monday, April 3, 2023, 07:00 AM
        end = datetime(2023, 4, 3, 20)   # Monday, April 3, 2023, 08:00 PM
        self.assertEqual(business_time_spent_in_seconds(start, end), 8 * 60 * 60)

    def test_across_multiple_weeks(self):
        start = datetime(2023, 4, 3, 9)  # Monday, April 3, 2024, 09:00 AM
        end = datetime(2023, 4, 17, 17)  # Monday, April 17, 2024, 05:00 PM
        # 10 business days in between
        self.assertEqual(business_time_spent_in_seconds(start, end), 11 * 8 * 60 * 60)

    def test_start_and_end_on_weekend(self):
        start = datetime(2023, 4, 8, 10)  # Saturday, April 8, 2023, 10:00 AM
        end = datetime(2023, 4, 9, 15)    # Sunday, April 9, 2023, 03:00 PM
        self.assertEqual(business_time_spent_in_seconds(start, end), 0)


class TestGetWeekIntervals(unittest.TestCase):
    def test_week_intervals(self):
        # Test with interval of 1 week
        intervals = get_week_intervals("2021-01-01", "2021-01-21", 1)
        expected_intervals = ["2021-01-01", "2021-01-08", "2021-01-15"]
        self.assertEqual(intervals, expected_intervals)

    def test_week_intervals_with_large_interval(self):
        # Test with interval of 3 weeks
        intervals = get_week_intervals("2021-01-01", "2021-02-26", 3)
        expected_intervals = ["2021-01-01", "2021-01-22", "2021-02-12"]
        self.assertEqual(intervals, expected_intervals)

    def test_week_intervals_same_start_end_date(self):
        # Test with the same start and end date
        intervals = get_week_intervals("2021-01-01", "2021-01-01", 1)
        expected_intervals = ["2021-01-01"]
        self.assertEqual(intervals, expected_intervals)

    def test_week_intervals_end_date_before_start_date(self):
        # Test with end date before start date
        intervals = get_week_intervals("2021-01-21", "2021-01-01", 1)
        expected_intervals = []
        self.assertEqual(intervals, expected_intervals)

    def test_week_intervals_with_zero_interval(self):
        # Test with interval of 0 weeks (should raise an error)
        with self.assertRaises(ValueError):
            get_week_intervals("2021-01-01", "2021-01-21", 0)



# This allows the test to be run from the command line
if __name__ == '__main__':
    unittest.main()