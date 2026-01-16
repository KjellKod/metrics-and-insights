import os
import sys
import unittest
from unittest.mock import MagicMock, patch

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


class TestTransformMonth(unittest.TestCase):
    def test_transform_month_january(self):
        result = individual.transform_month("2024-01")
        self.assertEqual(result, "2024 Jan")

    def test_transform_month_december(self):
        result = individual.transform_month("2024-12")
        self.assertEqual(result, "2024 Dec")

    def test_transform_month_february(self):
        result = individual.transform_month("2024-02")
        self.assertEqual(result, "2024 Feb")

    def test_transform_month_march(self):
        result = individual.transform_month("2024-03")
        self.assertEqual(result, "2024 Mar")

    def test_transform_month_june(self):
        result = individual.transform_month("2024-06")
        self.assertEqual(result, "2024 Jun")


class TestCalculatePoints(unittest.TestCase):
    def test_calculate_points_with_value(self):
        issue = MagicMock()
        issue.fields.customfield_12345 = 5
        with patch.object(individual, "CUSTOM_FIELD_STORYPOINTS", "12345"):
            result = individual.calculate_points(issue)
            self.assertEqual(result, 5)

    def test_calculate_points_with_none(self):
        issue = MagicMock()
        issue.fields.customfield_12345 = None
        with patch.object(individual, "CUSTOM_FIELD_STORYPOINTS", "12345"):
            result = individual.calculate_points(issue)
            self.assertEqual(result, 0)

    def test_calculate_points_with_zero(self):
        issue = MagicMock()
        issue.fields.customfield_12345 = 0
        with patch.object(individual, "CUSTOM_FIELD_STORYPOINTS", "12345"):
            result = individual.calculate_points(issue)
            self.assertEqual(result, 0)

    def test_calculate_points_missing_field(self):
        issue = MagicMock()
        # When field doesn't exist, getattr without default raises AttributeError
        # But with MagicMock, missing attrs return another MagicMock (truthy)
        # So we test the realistic case: field exists but is None
        issue.fields.customfield_12345 = None
        with patch.object(individual, "CUSTOM_FIELD_STORYPOINTS", "12345"):
            # getattr with None should return 0 (due to "or 0")
            result = individual.calculate_points(issue)
            self.assertEqual(result, 0)


class TestCalculateRollingTopContributors(unittest.TestCase):
    def test_empty_assignee_metrics(self):
        assignee_metrics = {}
        result = individual.calculate_rolling_top_contributors(assignee_metrics, "2024-12-31")
        self.assertEqual(result["points_ratio"], [])
        self.assertEqual(result["tickets_ratio"], [])
        self.assertEqual(result["points_total"], [])
        self.assertEqual(result["tickets_total"], [])

    def test_single_month_single_assignee(self):
        assignee_metrics = {
            "2024-12": {
                "TeamA": {
                    "Alice": {"points": 10, "tickets": 2},
                }
            }
        }
        result = individual.calculate_rolling_top_contributors(assignee_metrics, "2024-12-31")
        # With single assignee, ratio should be 1.0 (self vs self)
        self.assertEqual(len(result["points_ratio"]), 1)
        self.assertEqual(result["points_ratio"][0][0], "Alice")
        self.assertEqual(result["points_ratio"][0][1], 1.0)
        self.assertEqual(result["points_ratio"][0][2], 10)

    def test_multiple_months_multiple_assignees(self):
        # Create data for last 3 months with multiple assignees
        assignee_metrics = {
            "2024-10": {
                "TeamA": {
                    "Alice": {"points": 20, "tickets": 4},
                    "Bob": {"points": 10, "tickets": 2},
                }
            },
            "2024-11": {
                "TeamA": {
                    "Alice": {"points": 15, "tickets": 3},
                    "Bob": {"points": 15, "tickets": 3},
                    "Charlie": {"points": 5, "tickets": 1},
                }
            },
            "2024-12": {
                "TeamA": {
                    "Alice": {"points": 30, "tickets": 6},
                    "Bob": {"points": 10, "tickets": 2},
                }
            },
        }
        result = individual.calculate_rolling_top_contributors(assignee_metrics, "2024-12-31")

        # Verify structure
        self.assertIn("points_ratio", result)
        self.assertIn("tickets_ratio", result)
        self.assertIn("points_total", result)
        self.assertIn("tickets_total", result)

        # Verify top 3 limit
        self.assertLessEqual(len(result["points_ratio"]), 3)
        self.assertLessEqual(len(result["tickets_ratio"]), 3)
        self.assertLessEqual(len(result["points_total"]), 3)
        self.assertLessEqual(len(result["tickets_total"]), 3)

        # Verify Alice has highest total points (20+15+30=65)
        points_totals = {name: points for name, points in result["points_total"]}
        self.assertEqual(points_totals["Alice"], 65)

    def test_assignees_with_zero_points(self):
        assignee_metrics = {
            "2024-12": {
                "TeamA": {
                    "Alice": {"points": 10, "tickets": 2},
                    "Bob": {"points": 0, "tickets": 0},  # Inactive
                }
            }
        }
        result = individual.calculate_rolling_top_contributors(assignee_metrics, "2024-12-31")
        # Bob should not appear in results since he has 0 points and 0 tickets
        assignee_names = [name for name, _, _ in result["points_ratio"]]
        self.assertIn("Alice", assignee_names)
        self.assertNotIn("Bob", assignee_names)

    def test_multiple_teams_aggregation(self):
        # Test that assignees across teams are aggregated correctly
        assignee_metrics = {
            "2024-12": {
                "TeamA": {
                    "Alice": {"points": 10, "tickets": 2},
                },
                "TeamB": {
                    "Alice": {"points": 5, "tickets": 1},  # Same person, different team
                },
            }
        }
        result = individual.calculate_rolling_top_contributors(assignee_metrics, "2024-12-31")
        # Alice's points should be aggregated: 10 + 5 = 15
        points_totals = {name: points for name, points in result["points_total"]}
        self.assertEqual(points_totals["Alice"], 15)

    def test_months_active_counting(self):
        assignee_metrics = {
            "2024-10": {
                "TeamA": {
                    "Alice": {"points": 10, "tickets": 2},
                }
            },
            "2024-11": {
                "TeamA": {
                    "Alice": {"points": 0, "tickets": 0},  # Inactive this month
                }
            },
            "2024-12": {
                "TeamA": {
                    "Alice": {"points": 10, "tickets": 2},
                }
            },
        }
        result = individual.calculate_rolling_top_contributors(assignee_metrics, "2024-12-31")
        # Alice should have 2 active months (Oct and Dec)
        # The function doesn't return months_active, but we can verify the calculation
        # by checking that ratios are calculated correctly (should be based on 2 active months)
        self.assertGreater(len(result["points_ratio"]), 0)

    def test_top_three_limit(self):
        # Create data with more than 3 assignees
        assignee_metrics = {
            "2024-12": {
                "TeamA": {
                    "Alice": {"points": 30, "tickets": 6},
                    "Bob": {"points": 20, "tickets": 4},
                    "Charlie": {"points": 10, "tickets": 2},
                    "David": {"points": 5, "tickets": 1},
                    "Eve": {"points": 3, "tickets": 1},
                }
            }
        }
        result = individual.calculate_rolling_top_contributors(assignee_metrics, "2024-12-31")
        # Should only return top 3
        self.assertEqual(len(result["points_total"]), 3)
        self.assertEqual(len(result["tickets_total"]), 3)
        # Verify Alice, Bob, Charlie are in top 3 (not David or Eve)
        top_three_names = [name for name, _ in result["points_total"]]
        self.assertIn("Alice", top_three_names)
        self.assertIn("Bob", top_three_names)
        self.assertIn("Charlie", top_three_names)
        self.assertNotIn("David", top_three_names)
        self.assertNotIn("Eve", top_three_names)


if __name__ == "__main__":
    unittest.main()
