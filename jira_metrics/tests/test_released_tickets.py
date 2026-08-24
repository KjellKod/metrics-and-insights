import contextlib
import io
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
# pylint: disable=wrong-import-position,import-error
import released_tickets


class TestParseArguments(unittest.TestCase):
    def test_missing_year_prints_help(self):
        output = io.StringIO()

        with patch.object(sys, "argv", ["released_tickets.py"]), contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:
                released_tickets.parse_arguments()

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("usage:", output.getvalue())
        self.assertIn("--year YYYY", output.getvalue())

    def test_year_is_required_input(self):
        with patch.object(sys, "argv", ["released_tickets.py", "--year", "2025"]):
            args = released_tickets.parse_arguments()

        self.assertEqual(args.year, 2025)


class TestYearDateRange(unittest.TestCase):
    def test_returns_selected_calendar_year(self):
        self.assertEqual(released_tickets.get_year_date_range(2025), ("2025-01-01", "2025-12-31"))


if __name__ == "__main__":
    unittest.main()
