import sys
import os
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch
from collections import defaultdict

# Add the parent directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
# import functions to test- execute with 
#  python3 -m unittest discover -s test -p "test_engineering_excellence.py"
from engineering_excellence import get_resolution_date, get_team, get_work_type, update_team_data, categorize_ticket, extract_engineering_excellence

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
        expected_date = datetime.strptime("2023-10-01T12:34:56.789+0000", "%Y-%m-%dT%H:%M:%S.%f%z")
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
        self.assertEqual(get_team(self.ticket), "mobile")

    def test_get_team_unknown(self):
        self.ticket.fields.project.key = "OTHER"
        self.ticket.fields.customfield_10075 = None
        self.assertEqual(get_team(self.ticket), "unknown")

    def test_get_team_specific(self):
        self.ticket.fields.project.key = "OTHER"
        self.ticket.fields.customfield_10075.value = "Backend"
        self.assertEqual(get_team(self.ticket), "Backend")

    def test_get_work_type_other(self):
        self.ticket.fields.customfield_10079 = None
        self.assertEqual(get_work_type(self.ticket), "Other")

    def test_get_work_type_specific(self):
        self.ticket.fields.customfield_10079.value = "Feature"
        self.assertEqual(get_work_type(self.ticket), "Feature")

    def test_update_team_data_engineering_excellence(self):
        team_data = {
            "mobile": {
                "2023-10": {
                    "engineering_excellence": 0,
                    "other": 0
                }
            }
        }
        update_team_data(team_data, "mobile", "2023-10", "Debt Reduction")
        self.assertEqual(team_data["mobile"]["2023-10"]["engineering_excellence"], 1)
        self.assertEqual(team_data["mobile"]["2023-10"]["other"], 0)

    def test_update_team_data_other(self):
        team_data = {
            "mobile": {
                "2023-10": {
                    "engineering_excellence": 0,
                    "other": 0
                }
            }
        }
        update_team_data(team_data, "mobile", "2023-10", "Feature")
        self.assertEqual(team_data["mobile"]["2023-10"]["engineering_excellence"], 0)
        self.assertEqual(team_data["mobile"]["2023-10"]["other"], 1)

    @patch('builtins.print')
    def test_categorize_ticket_no_resolution_date(self, mock_print):
        self.ticket.key = "TICKET-1"
        self.ticket.changelog.histories = []
        team_data = {}
        categorize_ticket(self.ticket, team_data)
        mock_print.assert_called_with("Ticket TICKET-1 has no resolution date")


def test_categorize_ticket_with_resolution_date(self):
        self.ticket.key = "TICKET-2"
        self.ticket.changelog.histories = [
            MagicMock(created="2023-10-01T12:34:56.789+0000", items=[
                MagicMock(field="status", toString="Released")
            ])
        ]
        self.ticket.fields.project.key = "MOB"
        self.ticket.fields.customfield_10079.value = "Debt Reduction"
        team_data = {
            "mobile": {
                "2023-10": {
                    "engineering_excellence": 0,
                    "other": 0
                }
            }
        }
        categorize_ticket(self.ticket, team_data)
        self.assertEqual(team_data["mobile"]["2023-10"]["engineering_excellence"], 1)
        self.assertEqual(team_data["mobile"]["2023-10"]["other"], 0)


class TestEngineeringExcellence(unittest.TestCase):
    """
    Somewhat convoluted test case for the extract_engineering_excellence function.
    """
    @patch('engineering_excellence.get_jira_instance')  # Mock the get_jira_instance function
    @patch('engineering_excellence.categorize_ticket')  # Mock the categorize_ticket function
    def test_extract_engineering_excellence(self, mock_categorize_ticket, mock_get_jira_instance):
        # Create a mock JIRA instance
        mock_jira = MagicMock()
        mock_get_jira_instance.return_value = mock_jira

        # Create a mock response for the search_issues method
        mock_issue = MagicMock()
        mock_issue.key = 'ONF-123'
        mock_issue.fields.issuetype.name = 'Task'
        mock_issue.fields.status.name = 'Released'
        mock_issue.changelog.histories = []

        mock_jira.search_issues.return_value = [mock_issue]

        # Define the start and end dates for the test
        start_date = '2023-01-01'
        end_date = '2023-12-31'

        # Mock the categorize_ticket function to assign the team name "MockTeam"
        def mock_categorize(ticket, team_data):
            team_data['MockTeam']['Task']['engineering_excellence'] += 1

        mock_categorize_ticket.side_effect = mock_categorize

        # Call the function with the test dates
        team_data = extract_engineering_excellence(start_date, end_date)

        # Check that the JQL query was constructed correctly
        expected_jql_query = f"project in (ONF, ENG, MOB) AND status changed to Released during ({start_date}, {end_date}) AND issueType in (Task, Bug, Story, Spike) ORDER BY updated ASC"
        mock_jira.search_issues.assert_called_once_with(expected_jql_query, maxResults=1000, expand='changelog')

        # Check that the team_data dictionary was populated correctly
        expected_team_data = defaultdict(lambda: defaultdict(lambda: {"engineering_excellence": 0, "other": 0}))
        expected_team_data['MockTeam']['Task']['engineering_excellence'] = 1

        self.assertEqual(team_data, expected_team_data)


if __name__ == '__main__':
    unittest.main()
