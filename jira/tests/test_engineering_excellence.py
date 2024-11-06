import sys
import os
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch
from collections import defaultdict

# Add the parent directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
# import functions to test- execute with
#  python3 -m unittest discover -s test -p "test_engineering_excellence.py"
# pylint: disable=wrong-import-position,import-error
from engineering_excellence import (
    get_resolution_date,
    get_team,
    get_work_type,
    update_team_data,
    categorize_ticket,
    extract_engineering_excellence,
)

from jira_utils import get_jira_instance


class TestGetResolutionDate(unittest.TestCase):
    def setUp(self):
        # Create a mock ticket object
        self.ticket = MagicMock()
        self.ticket.changelog.histories = []

    def test_resolution_date_found(self):
        # Create a mock history item with the status "Released"
        history_item = MagicMock()
        history_item.field = "status"
        history_item.toString = "Released"

        # Create a mock history with the created date
        history = MagicMock()
        history.created = "2023-10-01T12:34:56.789+0000"
        history.items = [history_item]

        # Add the mock history to the ticket's changelog
        self.ticket.changelog.histories = [history]

        # Call the function and check the result
        expected_date = datetime.strptime(
            "2023-10-01T12:34:56.789+0000", "%Y-%m-%dT%H:%M:%S.%f%z"
        )
        result = get_resolution_date(self.ticket)
        self.assertEqual(result, expected_date)

    def test_resolution_date_not_found(self):
        # Create a mock history item with a different status
        history_item = MagicMock()
        history_item.field = "status"
        history_item.toString = "In Progress"

        # Create a mock history with the created date
        history = MagicMock()
        history.created = "2023-10-01T12:34:56.789+0000"
        history.items = [history_item]

        # Add the mock history to the ticket's changelog
        self.ticket.changelog.histories = [history]

        # Call the function and check the result
        result = get_resolution_date(self.ticket)
        self.assertIsNone(result)

    def test_no_histories(self):
        # Ensure the ticket has no histories
        self.ticket.changelog.histories = []

        # Call the function and check the result
        result = get_resolution_date(self.ticket)
        self.assertIsNone(result)


class TestTicketFunctions(unittest.TestCase):

    def setUp(self):
        self.ticket = MagicMock()
        self.ticket.fields = MagicMock()
        self.ticket.fields.project = MagicMock()
        self.ticket.fields.customfield_10075 = MagicMock()
        self.ticket.fields.customfield_10079 = MagicMock()

    def test_get_team_mobile(self):
        self.ticket.fields.project.key = "MOB"
        self.ticket.fields.customfield_10075 = None
        self.assertEqual(get_team(self.ticket), "Mobile")

    def test_get_team_unknown(self):
        self.ticket.fields.project.key = "UNKNOWN"
        self.ticket.fields.customfield_10075 = None
        self.assertEqual(get_team(self.ticket), "Unknown")

    def test_get_team_specific(self):
        self.ticket.fields.project.key = "UNKNOWN"
        self.ticket.fields.customfield_10075.value = "Backend"
        self.assertEqual(get_team(self.ticket), "Backend")

    def test_get_work_type_product(self):
        self.ticket.fields.customfield_10079 = None
        self.assertEqual(get_work_type(self.ticket), "Product")

    def test_get_work_type_specific(self):
        self.ticket.fields.customfield_10079.value = "Feature"
        self.assertEqual(get_work_type(self.ticket), "Feature")

    def test_update_team_data_engineering_excellence(self):
        team_data = {
            "all": {"2023-10": {"engineering_excellence": 0, "product": 0}},
            "mobile": {"2023-10": {"engineering_excellence": 0, "product": 0}},
        }
        update_team_data(team_data, "mobile", "2023-10", "Debt Reduction")
        self.assertEqual(team_data["mobile"]["2023-10"]["engineering_excellence"], 1)
        self.assertEqual(team_data["mobile"]["2023-10"]["product"], 0)

    @patch("builtins.print")
    def test_categorize_ticket_no_resolution_date(self, mock_print):
        self.ticket.key = "TICKET-1"
        self.ticket.changelog.histories = []
        team_data = {}
        categorize_ticket(self.ticket, team_data)
        mock_print.assert_called_with("Ticket TICKET-1 has no resolution date")

    def test_categorize_ticket_with_resolution_date(self):
        self.ticket.key = "TICKET-2"
        self.ticket.changelog.histories = [
            MagicMock(
                created="2023-10-01T12:34:56.789+0000",
                items=[MagicMock(field="status", toString="Released")],
            )
        ]
        self.ticket.fields.project.key = "MOB"
        self.ticket.fields.customfield_10075.value = "Mobile"
        self.ticket.fields.customfield_10079.value = "Debt Reduction"

        team_data = {
            "all": {
                "2023-10": {"engineering_excellence": 0, "product": 0, "tickets": []}
            },
            "Mobile": {
                "2023-10": {"engineering_excellence": 0, "product": 0, "tickets": []}
            },
        }
        categorize_ticket(self.ticket, team_data)
        self.assertEqual(team_data["Mobile"]["2023-10"]["engineering_excellence"], 1)
        self.assertEqual(team_data["Mobile"]["2023-10"]["product"], 0)


if __name__ == "__main__":
    unittest.main()
