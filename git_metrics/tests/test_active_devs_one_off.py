import unittest
from unittest.mock import patch, MagicMock
from active_devs_one_off import validate_env_variables, fetch_repositories, fetch_commit_activity


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

    @patch("active_devs_one_off.requests.post")
    def test_fetch_repositories(self, mock_post):
        # Mock the response from GitHub API
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {"organization": {"repositories": {"nodes": [{"name": "repo1"}, {"name": "repo2"}]}}}
        }
        mock_post.return_value = mock_response

        api_config = {"url": "fake_url", "headers": {}}
        org_name = "fake_org"
        repos = fetch_repositories(api_config, org_name)
        self.assertEqual(repos, ["repo1", "repo2"])

    @patch("active_devs_one_off.requests.post")
    def test_fetch_commit_activity(self, mock_post):
        # Mock the response from GitHub API
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {
                "repository": {
                    "defaultBranchRef": {
                        "target": {
                            "history": {
                                "nodes": [
                                    {"author": {"user": {"login": "dev1"}}},
                                    {"author": {"user": {"login": "dev2"}}},
                                ]
                            }
                        }
                    }
                }
            }
        }
        mock_post.return_value = mock_response

        api_config = {"url": "fake_url", "headers": {}}
        org_name = "fake_org"
        repo_name = "repo1"
        since_date = datetime(2023, 1, 1)
        authors = fetch_commit_activity(api_config, org_name, repo_name, since_date)
        self.assertEqual(authors, {"dev1", "dev2"})


if __name__ == "__main__":
    unittest.main()
