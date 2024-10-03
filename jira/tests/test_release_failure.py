import os
import sys
import unittest
from unittest.mock import patch, MagicMock
from collections import defaultdict
from io import StringIO

# Add the parent directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from release_failure import (
    extract_linked_tickets,
    count_failed_releases,
    process_release_tickets,
    print_total_failure_percentage
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
 
    def test_process_release_tickets(self):
        mock_ticket = MagicMock()
        mock_ticket.key = 'TICKET-1'
        mock_ticket.changelog.histories = [
            MagicMock(created='2023-01-02T00:00:00.000+0000', items=[
                MagicMock(field='status', fromString='Released', toString='To Release')
            ]),
            MagicMock(created='2023-01-01T00:00:00.000+0000', items=[
                MagicMock(field='status', fromString='Open', toString='Released')
            ])
        ]
        mock_ticket.fields.issuelinks = [
            MagicMock(spec=['outwardIssue'], outwardIssue=MagicMock(key='LINKED-1')),
            MagicMock(spec=['outwardIssue'], outwardIssue=MagicMock(key='LINKED-2')),
        ]

        release_info, failed_releases_per_month, failed_releaselinked_tickets_count_per_month, total_linked_tickets_count_per_month, total_releases_per_month, exceptions = process_release_tickets([mock_ticket])
        
        self.assertEqual(len(release_info), 1)
        self.assertEqual(failed_releases_per_month['2023-01'], 1)
        self.assertEqual(failed_releaselinked_tickets_count_per_month['2023-01'], 2)
        self.assertEqual(total_linked_tickets_count_per_month['2023-01'], 2)
        self.assertEqual(total_releases_per_month['2023-01'], 1)

    def test_print_total_failure_percentage(self):
        total_releases_per_month = defaultdict(int, {'2023-01': 1})
        failed_releases_per_month = defaultdict(int, {'2023-01': 1})

        expected_output = "\nTotal release failure percentage for the whole time period: 100.00%\n"

        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            print_total_failure_percentage(total_releases_per_month, failed_releases_per_month)
            self.assertEqual(mock_stdout.getvalue(), expected_output)


if __name__ == '__main__':
    unittest.main()
