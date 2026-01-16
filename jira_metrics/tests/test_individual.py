import os
import sys
import unittest
from unittest.mock import patch

# Add the parent directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
# pylint: disable=wrong-import-position,import-error
import individual


class TestConstructJql(unittest.TestCase):
    @patch("individual.get_completion_statuses", return_value=["released", "done"])
    def test_construct_jql_for_team(self, _mock_statuses):
        with patch.object(individual, "projects", ["ABC", "DEF"]):
            jql = individual.construct_jql(
                team_name="Swedes",
                project_key=None,
                start_date="2024-01-01",
                end_date="2024-12-31",
            )

        self.assertIn("project IN ('ABC', 'DEF')", jql)
        self.assertIn('status IN ("Released", "Done")', jql)
        self.assertIn('status CHANGED TO ("Released", "Done")', jql)
        self.assertIn("DURING ('2024-01-01', '2024-12-31')", jql)
        self.assertIn('"Team[Dropdown]" = "Swedes"', jql)
        self.assertTrue(jql.endswith("ORDER BY updated ASC"))

    @patch("individual.get_completion_statuses", return_value=["released", "done"])
    def test_construct_jql_for_project(self, _mock_statuses):
        jql = individual.construct_jql(
            team_name=None,
            project_key="SWE",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )

        self.assertIn("project = 'SWE'", jql)
        self.assertIn('status IN ("Released", "Done")', jql)
        self.assertIn('status CHANGED TO ("Released", "Done")', jql)
        self.assertIn("DURING ('2024-01-01', '2024-12-31')", jql)
        self.assertTrue(jql.endswith("ORDER BY updated ASC"))

    def test_construct_jql_requires_filter(self):
        with self.assertRaises(ValueError):
            individual.construct_jql(
                team_name=None,
                project_key=None,
                start_date="2024-01-01",
                end_date="2024-12-31",
            )


if __name__ == "__main__":
    unittest.main()
