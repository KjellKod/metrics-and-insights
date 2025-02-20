import unittest
import sys
import os
from unittest.mock import MagicMock
from datetime import datetime, timezone, timedelta
import pytz
from jira.resources import Issue
from collections import defaultdict
from unittest.mock import patch, MagicMock

# Add the parent directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
# pylint: disable=wrong-import-position,import-error
from jira_metrics.bug_stats import (
    build_jql_queries,
    fetch_bug_statistics,
    export_to_csv,
    validate_years,
    generate_yearly_report,
    setup_logging,
)

import sys
import os


class TestBugStats(unittest.TestCase):
    def test_validate_years(self):
        """Test year validation"""
        current_year = datetime.now().year

        # Valid cases
        validate_years(2020, 2021)
        validate_years(current_year, current_year)

        # Invalid cases
        with self.assertRaises(ValueError):
            validate_years(1899, 2020)
        with self.assertRaises(ValueError):
            validate_years(2020, current_year + 1)
        with self.assertRaises(ValueError):
            validate_years(2021, 2020)


def test_build_jql_queries():
    """Test the JQL query builder function"""
    projects = ["PROJ1", "PROJ2"]
    year = 2023

    # Test H1
    queries = build_jql_queries(year, projects)
    assert "created >= '2023-01-01'" in queries["created"]
    assert "created <= '2023-12-31'" in queries["created"]
    assert "project in ('PROJ1', 'PROJ2')" in queries["created"]


@patch("jira_metrics.bug_stats.get_tickets_from_jira")
def test_fetch_bug_statistics(mock_get_tickets):
    """Test the core statistics fetching logic"""
    # Setup mock data
    mock_ticket = MagicMock()
    mock_ticket.fields.project.key = "PROJ1"
    mock_ticket.key = "BUG-123"
    mock_get_tickets.return_value = [mock_ticket]

    # Test
    stats = fetch_bug_statistics(2023, ["PROJ1"])

    assert stats["PROJ1"]["created"]["count"] == 1
    assert stats["PROJ1"]["created"]["tickets"] == ["BUG-123"]


def test_export_to_csv(tmp_path):
    """Test CSV export functionality"""
    # Setup test data
    stats = {
        2023: {
            "PROJ1": {
                "created": {"count": 5, "tickets": []},
                "closed": {"count": 3, "tickets": []},
                "open_eoy": {"count": 2, "tickets": []},
            }
        }
    }

    # Test export
    test_file = tmp_path / "test.csv"
    export_to_csv(stats, filename=test_file)

    # Verify file content
    with open(test_file, "r") as f:
        content = f.read()
        assert "2023" in content
        assert "PROJ1 Bugs Created" in content
        assert "5" in content


@patch("jira_metrics.bug_stats.fetch_bug_statistics")
def test_generate_yearly_report(mock_fetch):
    """Test the yearly report generation"""
    # Setup mock
    mock_fetch.return_value = {"PROJ1": {"created": {"count": 1}}}

    # Test
    report = generate_yearly_report(2020, 2021, ["PROJ1"])

    assert 2020 in report
    assert 2021 in report
    assert "PROJ1" in report[2020]


def test_setup_logging(capsys):
    """Test logging setup"""
    logger = setup_logging()
    logger.info("Test message")
    captured = capsys.readouterr()
    assert "Test message" in captured.out
