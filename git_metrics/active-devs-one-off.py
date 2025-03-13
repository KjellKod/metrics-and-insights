import os
import sys
import logging
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

"""
Active Developers Report Generator
================================

This script generates a report of active developers across GitHub repositories
within your organization over the last 60 days. It uses GitHub's GraphQL API
to efficiently fetch commit data and identify unique contributors.

I needed something like this to fetch which developers are most active, as we have some that are more administrative than active. 
For the active ones we wanted to pay for some tool usage and finding out how many "seats" we needed and to whom was important. 
(I could not at the time find an easy way to extract this from Github)

Features:
- Fetches commit activity across multiple repositories
- Identifies unique contributors from commit history
- Supports both organization-wide scanning and specific repository lists
- Uses GraphQL for efficient API calls
- Includes proper error handling and logging

Setup Requirements:
-----------------
1. Create a .env file in the root directory with the following variables:

    GITHUB_TOKEN_READONLY_WEB=your_github_personal_access_token
    GITHUB_METRIC_OWNER_OR_ORGANIZATION=your_organization_name
    
    # Optional: Specific repositories to scan (comma-separated)
    # If not provided, will fetch all repositories from the organization
    GITHUB_METRIC_REPOS=awesome-service-api,cool-frontend-app,internal-tools-repo,user-management-service

2. Ensure you have required Python packages installed:
    - requests
    - python-dotenv

Usage:
------
Simply run the script:
    python active-devs-one-off.py

Output:
-------
The script will output:
- List of repositories being processed
- Active developers found in the last 60 days
- Total count of active developers

Example Output:
-------------
2024-01-20 10:30:15 - INFO - Using repositories from environment variable: 4 repos
2024-01-20 10:30:16 - INFO - Processing repository: awesome-service-api
2024-01-20 10:30:17 - INFO - Processing repository: cool-frontend-app
...
2024-01-20 10:30:20 - INFO - Active Developers in the last 2 months:
2024-01-20 10:30:20 - INFO - - alice.developer
2024-01-20 10:30:20 - INFO - - bob.coder
2024-01-20 10:30:20 - INFO - - charlie.engineer
2024-01-20 10:30:20 - INFO - Total active developers: 3

Notes:
-----
- The script uses a 60-day lookback period by default
- Only commits to the default branch are considered
- The GitHub token needs 'repo' access to read private repositories
"""

# Load environment variables
load_dotenv()


def setup_logging():
    """Configure logging settings."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    return logging.getLogger(__name__)


def validate_env_variables():
    """Validate required environment variables and return their values."""
    logger = logging.getLogger(__name__)
    required_vars = {
        "GITHUB_TOKEN_READONLY_WEB": "GitHub access token",
        "GITHUB_METRIC_OWNER_OR_ORGANIZATION": "GitHub organization name",
        # New optional variable for repository list
        "GITHUB_METRIC_REPOS": "Optional: Comma-separated list of repositories",
    }

    missing_vars = []
    env_values = {}

    for var, description in required_vars.items():
        value = os.environ.get(var)
        if not value and var != "GITHUB_METRIC_REPOS":  # GITHUB_METRIC_REPOS is optional
            missing_vars.append(f"{var} ({description})")
        env_values[var] = value

    if missing_vars:
        logger.error("Missing required environment variables:\n%s", "\n".join(f"- {var}" for var in missing_vars))
        raise ValueError("Missing required environment variables")

    return env_values


def setup_github_api(access_token):
    """Setup GitHub API configuration."""
    return {
        "url": "https://api.github.com/graphql",
        "headers": {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github.v4+json",
        },
    }


def execute_graphql_query(api_config, query, variables):
    """Execute a GraphQL query and return the response data."""
    try:
        response = requests.post(
            api_config["url"], headers=api_config["headers"], json={"query": query, "variables": variables}
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error("GraphQL query failed: %s", str(e))
        raise


def fetch_repositories(api_config, org_name):
    """Fetch all repositories in the organization using GraphQL"""
    logger = logging.getLogger(__name__)
    query = """
    query ($org: String!) {
        organization(login: $org) {
            repositories(first: 100) {
                nodes {
                    name
                }
            }
        }
    }
    """
    variables = {"org": org_name}

    try:
        data = execute_graphql_query(api_config, query, variables)
        return [repo["name"] for repo in data["data"]["organization"]["repositories"]["nodes"]]
    except Exception as e:
        logger.error("Failed to fetch repositories: %s", str(e))
        return None


def fetch_commit_activity(api_config, org_name, repo_name, since_date):
    """Fetch commit history for a given repository"""
    logger = logging.getLogger(__name__)
    query = """
    query ($owner: String!, $repo: String!, $since: GitTimestamp!) {
        repository(owner: $owner, name: $repo) {
            defaultBranchRef {
                target {
                    ... on Commit {
                        history(since: $since, first: 100) {
                            nodes {
                                author {
                                    user {
                                        login
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    """
    variables = {"owner": org_name, "repo": repo_name, "since": since_date.isoformat()}

    try:
        data = execute_graphql_query(api_config, query, variables)

        commit_authors = set()
        history = data["data"]["repository"]["defaultBranchRef"]["target"]["history"]["nodes"]
        for commit in history:
            author = commit.get("author", {}).get("user", {})
            if author and author.get("login"):
                commit_authors.add(author["login"])
        return commit_authors
    except Exception as e:
        logger.error("Failed to fetch commit activity for %s: %s", repo_name, str(e))
        return set()


def main():
    """Main function to gather developer activity"""
    logger = setup_logging()
    try:
        env_vars = validate_env_variables()
        api_config = setup_github_api(env_vars["GITHUB_TOKEN_READONLY_WEB"])
        org_name = env_vars["GITHUB_METRIC_OWNER_OR_ORGANIZATION"]

        # Calculate date range (last 2 months)
        since_date = datetime.utcnow() - timedelta(days=60)

        # Get repositories
        if env_vars.get("GITHUB_METRIC_REPOS"):
            repositories = [repo.strip() for repo in env_vars["GITHUB_METRIC_REPOS"].split(",")]
            logger.info("Using repositories from environment variable: %d repos", len(repositories))
        else:
            repositories = fetch_repositories(api_config, org_name)
            if not repositories:
                raise ValueError("No repositories found")
            logger.info("Fetched repositories from GitHub API: %d repos", len(repositories))

        active_developers = set()
        for repo in repositories:
            logger.info("Processing repository: %s", repo)
            contributors = fetch_commit_activity(api_config, org_name, repo, since_date)
            active_developers.update(contributors)

        logger.info("\nActive Developers in the last 2 months:")
        for dev in sorted(active_developers):
            logger.info("- %s", dev)
        logger.info("Total active developers: %d", len(active_developers))

    except Exception as e:
        logger.error("An error occurred: %s", str(e), exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
