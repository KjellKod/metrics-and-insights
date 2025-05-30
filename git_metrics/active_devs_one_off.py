import os
import sys
import logging
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from lines_changed import setup_logging
import requests

# pylint: disable=pointless-string-statement
"""
Active Repositories Report Generator
================================

This script generates a report of repositories with recent pull request activity
within your organization over the last 60 days. It uses GitHub's GraphQL API
to efficiently fetch repository and pull request data.

Features:
- Fetches repository and pull request activity
- Identifies repositories with recent PRs
- Uses GraphQL for efficient API calls
- Includes proper error handling and logging

Setup Requirements:
-----------------
1. Create a .env file in the root directory with the following variables:

    GITHUB_TOKEN_READONLY_WEB=your_github_personal_access_token
    GITHUB_METRIC_OWNER_OR_ORGANIZATION=your_organization_name

Usage:
------
Simply run the script:
    python repo-activity-report.py

Output:
-------
The script will output:
- List of repositories with PR activity in the last 60 days
- Details including last PR date, recent PR count, and total PR count
- Summary statistics
"""

# Load environment variables
load_dotenv()


# pylint: disable=too-many-locals
def fetch_active_repositories(api_config, org_name, since_date):
    """Fetch repositories with PR activity since the given date"""
    logger = logging.getLogger(__name__)
    query = """
    query ($org: String!) {
        organization(login: $org) {
            repositories(first: 100) {
                nodes {
                    name
                    pullRequests(states: [OPEN, CLOSED, MERGED], 
                                first: 10,  # Increased to get more recent PRs
                                orderBy: {field: UPDATED_AT, direction: DESC}) {
                        nodes {
                            updatedAt
                            number
                        }
                        totalCount
                    }
                    defaultBranchRef {
                        name
                    }
                }
            }
        }
    }
    """

    variables = {"org": org_name}

    try:
        response = requests.post(
            api_config["url"], headers=api_config["headers"], json={"query": query, "variables": variables}, timeout=120
        )
        response.raise_for_status()
        data = response.json()

        if "errors" in data:
            logger.error("GraphQL errors: %s", data["errors"])
            return []

        if "data" not in data or not data["data"]:
            logger.error("No data in response: %s", data)
            return []

        active_repos = []
        repositories = data["data"]["organization"]["repositories"]["nodes"]

        for repo in repositories:
            if not repo.get("defaultBranchRef"):
                continue

            prs = repo.get("pullRequests", {})
            pr_nodes = prs.get("nodes", [])

            # Filter PRs by date
            recent_prs = []
            for pr in pr_nodes:
                pr_date = datetime.fromisoformat(pr["updatedAt"].replace("Z", "+00:00"))
                if pr_date >= since_date:
                    recent_prs.append(pr)

            if recent_prs:  # Only include repos with recent PRs
                last_pr_date = datetime.fromisoformat(recent_prs[0]["updatedAt"].replace("Z", "+00:00"))
                active_repos.append(
                    {
                        "name": repo["name"],
                        "default_branch": repo["defaultBranchRef"]["name"],
                        "last_pr_date": last_pr_date,
                        "recent_pr_count": len(recent_prs),
                        "total_pr_count": prs.get("totalCount", 0),
                    }
                )

        return active_repos

    except Exception as e:
        logger.error("Failed to fetch repository activity: %s", str(e))
        logger.debug("Full response: %s", response.text if "response" in locals() else "No response")
        return []


def main():
    """Main function to identify active repositories"""
    logger = setup_logging()
    try:
        # Validate environment variables
        token = os.getenv("GITHUB_TOKEN_READONLY_WEB")
        org_name = os.getenv("GITHUB_METRIC_OWNER_OR_ORGANIZATION")

        if not token or not org_name:
            raise ValueError("Missing required environment variables")

        api_config = {
            "url": "https://api.github.com/graphql",
            "headers": {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github.v4+json",
            },
        }

        since_date = datetime.now(timezone.utc) - timedelta(days=60)

        logger.info("Fetching repositories with PR activity since %s", since_date.date())

        active_repos = fetch_active_repositories(api_config, org_name, since_date)

        if not active_repos:
            logger.info("No repositories found with PR activity in the last 60 days")
            return

        active_repos.sort(key=lambda x: x["last_pr_date"], reverse=True)

        logger.info("\nRepositories with PR activity in the last 60 days:")
        for repo in active_repos:
            logger.info(
                "- %s (last PR: %s, recent PRs: %d, total PRs: %d)",
                repo["name"],
                repo["last_pr_date"].strftime("%Y-%m-%d"),
                repo["recent_pr_count"],
                repo["total_pr_count"],
            )

        logger.info("\nSummary:")
        logger.info("Total active repositories: %d", len(active_repos))
        logger.info("Organization: %s", org_name)
        logger.info(
            "Time period: %s to %s", since_date.strftime("%Y-%m-%d"), datetime.now(timezone.utc).strftime("%Y-%m-%d")
        )

    except Exception as e:
        logger.error("An error occurred: %s", str(e), exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
