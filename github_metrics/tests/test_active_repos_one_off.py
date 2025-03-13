import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta, timezone
from active_repos_one_off import fetch_active_repositories

class TestActiveReposOneOff(unittest.TestCase):
    @patch('active_repos_one_off.requests.post')
    def test_fetch_active_repositories_success(self, mock_post):
        # Mock successful API response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {
                "organization": {
                    "repositories": {
                        "nodes": [
                            {
                                "name": "repo1",
                                "pullRequests": {
                                    "nodes": [
                                        {"updatedAt": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(), "number": 1}
                                    ],
                                    "totalCount": 1
                                },
                                "defaultBranchRef": {"name": "main"}
                            }
                        ]
                    }
                }
            }
        }
        mock_post.return_value = mock_response

        api_config = {
            "url": "https://api.github.com/graphql",
            "headers": {
                "Authorization": "Bearer test_token",
                "Accept": "application/vnd.github.v4+json",
            },
        }
        org_name = "test_org"
        since_date = datetime.now(timezone.utc) - timedelta(days=60)

        active_repos = fetch_active_repositories(api_config, org_name, since_date)

        self.assertEqual(len(active_repos), 1)
        self.assertEqual(active_repos[0]['name'], 'repo1')
        self.assertEqual(active_repos[0]['recent_pr_count'], 1)

    @patch('active_repos_one_off.requests.post')
    def test_fetch_active_repositories_no_data(self, mock_post):
        # Mock API response with no data
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": {"organization": {"repositories": {"nodes": []}}}}
        mock_post.return_value = mock_response

        api_config = {
            "url": "https://api.github.com/graphql",
            "headers": {
                "Authorization": "Bearer test_token",
                "Accept": "application/vnd.github.v4+json",
            },
        }
        org_name = "test_org"
        since_date = datetime.now(timezone.utc) - timedelta(days=60)

        active_repos = fetch_active_repositories(api_config, org_name, since_date)

        self.assertEqual(len(active_repos), 0)

    @patch('active_repos_one_off.requests.post')
    def test_fetch_active_repositories_error_handling(self, mock_post):
        # Mock API response with an error
        mock_response = MagicMock()
        mock_response.json.return_value = {"errors": [{"message": "Some error"}]}
        mock_post.return_value = mock_response

        api_config = {
            "url": "https://api.github.com/graphql",
            "headers": {
                "Authorization": "Bearer test_token",
                "Accept": "application/vnd.github.v4+json",
            },
        }
        org_name = "test_org"
        since_date = datetime.now(timezone.utc) - timedelta(days=60)

        active_repos = fetch_active_repositories(api_config, org_name, since_date)

        self.assertEqual(len(active_repos), 0)

if __name__ == '__main__':
    unittest.main()