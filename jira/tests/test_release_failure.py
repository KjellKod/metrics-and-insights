import os
import sys
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime

# Add the parent directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from release_failure import (
    extract_linked_tickets,
    count_failed_releases,
    analyze_release_tickets
)


"""
python3 -m unittest discover -v -s tests -p test_failed_releases.py
"""

class TestReleaseFailure(unittest.TestCase):


    def test_extract_linked_tickets(self):
        mock_issue = MagicMock()
        # MagicMock will return true for `hasattr` for any attribute
        # so we need to specify the spec to ensure the attribute is present
        mock_issue.fields.issuelinks = [
            MagicMock(spec=['outwardIssue'], outwardIssue=MagicMock(key='LINKED-1')),
            MagicMock(spec=['inwardIssue'], inwardIssue=MagicMock(key='IGNORE-1')),
            MagicMock(spec=['outwardIssue'], outwardIssue=MagicMock(key='LINKED-2')),
        ]
        linked_tickets = extract_linked_tickets(mock_issue)
        self.assertEqual(linked_tickets, ['LINKED-1', 'LINKED-2'])


    def test_count_failed_releases(self):
        mock_issue = MagicMock()
        mock_issue.changelog.histories = [
            MagicMock(created='2023-01-02T00:00:00.000+0000', items=[
                MagicMock(field='status', fromString='Released', toString='To Release')
            ]),
            MagicMock(created='2023-01-01T00:00:00.000+0000', items=[
                MagicMock(field='status', fromString='Open', toString='Released')
            ])
        ]
        fail_count, release_events = count_failed_releases(mock_issue)
        self.assertEqual(fail_count, 1)
        self.assertEqual(len(release_events), 1)
        self.assertTrue(release_events[0][1])
 
    @patch('release_failure.get_release_tickets')
    @patch('release_failure.extract_linked_tickets')
    @patch('release_failure.count_failed_releases')
    def test_analyze_release_tickets(self, mock_count_failed_releases, mock_extract_linked_tickets, mock_get_release_tickets):
        mock_get_release_tickets.return_value = [MagicMock(key='TICKET-1')]
        mock_extract_linked_tickets.return_value = ['LINKED-1', 'LINKED-2']
        mock_count_failed_releases.return_value = (1, [(datetime(2023, 1, 1), True)])

        with patch('builtins.print') as mock_print:
            analyze_release_tickets('2023-01-01', '2023-01-31')
            mock_print.assert_called()

if __name__ == '__main__':
    unittest.main()
