"""
date, timezone, workdays conversion and handling
"""

from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta

import json
import numpy as np


def datetime_serializer(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    elif isinstance(obj, np.int64):
        return int(obj)
    else:
        raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")


# Function to calculate resolution_date based on weeks_back input
def get_resolution_date(weeks_back):
    return (date.today() - timedelta(weeks=weeks_back)).strftime("%Y-%m-%d")


class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super(DateTimeEncoder, self).default(obj)


def parse_date(date_str):
    if date_str is not None:
        return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S.%f%z")
    return None


def seconds_to_hms(seconds):
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return hours, minutes, seconds


def business_time_spent_in_seconds(start, end):
    weekdays = [0, 1, 2, 3, 4]  # Monday to Friday
    total_business_seconds = 0
    seconds_in_workday = 8 * 60 * 60  # 8 hours * 60 minutes * 60 seconds

    current = start
    while current <= end:
        if current.weekday() in weekdays:
            day_end = current.replace(hour=23, minute=59)
            remaining_time_today = day_end - current

            if current.date() != end.date():
                total_business_seconds += min(remaining_time_today.total_seconds(), seconds_in_workday)
                current += timedelta(days=1)
                current = current.replace(hour=0, minute=0)
            else:
                remaining_time_on_last_day = end - current
                total_business_seconds += min(remaining_time_on_last_day.total_seconds(), seconds_in_workday)
                break
        else:
            current += timedelta(days=1)
            current = current.replace(hour=0, minute=0)

    return total_business_seconds


def get_week_intervals(minimal_date, maximal_date, interval):
    minimal_date = datetime.strptime(minimal_date, "%Y-%m-%d")
    maximal_date = datetime.strptime(maximal_date, "%Y-%m-%d")

    intervals = []

    current_date = minimal_date
    while current_date <= maximal_date:
        intervals.append(current_date.strftime("%Y-%m-%d"))

        # Use `relativedelta` to add interval number of weeks
        current_date += relativedelta(weeks=+interval)

    return intervals
