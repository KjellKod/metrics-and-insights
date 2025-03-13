import sys
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

# Add the parent directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Update the import statement to use relative path
# pylint: disable=wrong-import-position,import-error
from git_metrics.active_devs_one_off import (
    validate_env_variables,
    fetch_active_repositories,
)  # Changed from git_metrics.active_devs_one_off


class TestActiveDevsOneOff(unittest.TestCase):

    @patch("active_devs_one_off.os.environ.get")
    def test_validate_env_variables(self, mock_get):
        # Test with all required environment variables
        mock_get.side_effect = lambda var: {
            "GITHUB_TOKEN_READONLY_WEB": "fake_token",
            "GITHUB_METRIC_OWNER_OR_ORGANIZATION": "fake_org",
            "GITHUB_METRIC_REPOS": "repo1,repo2",
        }.get(var)
        env_vars = validate_env_variables()
        self.assertEqual(env_vars["GITHUB_TOKEN_READONLY_WEB"], "fake_token")
        self.assertEqual(env_vars["GITHUB_METRIC_OWNER_OR_ORGANIZATION"], "fake_org")
        self.assertEqual(env_vars["GITHUB_METRIC_REPOS"], "repo1,repo2")

        # Test with missing required environment variables
        mock_get.side_effect = lambda var: None if var == "GITHUB_TOKEN_READONLY_WEB" else "value"
        with self.assertRaises(ValueError):
            validate_env_variables()

    @patch("git_metrics.active_devs_one_off.requests.post")
    def test_fetch_active_repositories(self, mock_post):
        # Create a mock API response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {
                "organization": {
                    "repositories": {
                        "nodes": [
                            {
                                "name": "repo1",
                                "pullRequests": {
                                    "nodes": [{"updatedAt": "2024-03-01T00:00:00Z", "number": 1}],
                                    "totalCount": 1,
                                },
                                "defaultBranchRef": {"name": "main"},
                            },
                            {
                                "name": "repo2",
                                "pullRequests": {"nodes": [], "totalCount": 0},
                                "defaultBranchRef": {"name": "main"},
                            },
                        ]
                    }
                }
            }
        }
        mock_post.return_value = mock_response

        # Test fetching active repositories
        api_config = {"url": "fake_url", "headers": {"Authorization": "Bearer fake_token"}}
        since_date = datetime.now(timezone.utc)
        active_repos = fetch_active_repositories(api_config, "fake_org", since_date)

        # Verify the results
        self.assertEqual(len(active_repos), 1)  # Only repo1 has PR activity
        self.assertEqual(active_repos[0]["name"], "repo1")
        self.assertEqual(active_repos[0]["pr_count"], 1)

        # Verify the API was called correctly
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertEqual(call_args[0][0], "fake_url")
        self.assertIn("query", call_args[1]["json"])
        self.assertIn("variables", call_args[1]["json"])


if __name__ == "__main__":
    unittest.main()
