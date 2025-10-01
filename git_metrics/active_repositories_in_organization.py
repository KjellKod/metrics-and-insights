import sys
import logging
import argparse
import os
from datetime import datetime, timedelta, timezone
import requests

# pylint: disable=pointless-string-statement
"""Active Repository Report Generator
================================

This script identifies repositories that have had recent activity (pushes or PRs)
within a specified time period across a GitHub organization.

Features:
- Fetches all repositories from an organization with proper pagination
- Shows both push activity and PR activity
- Uses GraphQL for efficient API calls
- Includes proper error handling and logging
- Sorts by most recent activity (push or PR)

Usage:
------
python git_metrics/active_repositories_in_organization.py --org ORGANIZATION --token-env TOKEN_VAR [--days DAYS]

Required Arguments:
  --org, -o          GitHub organization name (e.g., 'onfleet', 'microsoft')
  --token-env, -t    Environment variable name containing GitHub personal access token

Optional Arguments:
  --days, -d         Number of days to look back for activity (default: 60)
  --verbose, -v      Enable verbose logging

Examples:
  export GITHUB_TOKEN=ghp_xxxxx
  python git_metrics/active_repositories_in_organization.py --org onfleet --token-env GITHUB_TOKEN
  python git_metrics/active_repositories_in_organization.py --org myorg --token-env GITHUB_TOKEN --days 30 --verbose
"""


def parse_github_date(date_str):
    """Parse GitHub date string to datetime object."""
    return datetime.fromisoformat(date_str.replace("Z", "+00:00"))


def setup_logging(verbose=False):
    """Configure logging settings."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    return logging.getLogger(__name__)


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Find repositories with recent activity in a GitHub organization",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  export GITHUB_TOKEN=ghp_xxxxx
  %(prog)s --org onfleet --token-env GITHUB_TOKEN
  %(prog)s --org myorg --token-env GITHUB_TOKEN --days 30 --verbose

Note: You can get a GitHub personal access token from:
https://github.com/settings/tokens
        """,
    )

    parser.add_argument("--org", "-o", required=True, help="GitHub organization name (e.g., 'onfleet', 'microsoft')")

    parser.add_argument(
        "--token-env", "-t", required=True, help="Environment variable name containing GitHub personal access token"
    )

    parser.add_argument(
        "--days", "-d", type=int, default=60, help="Number of days to look back for activity (default: 60)"
    )

    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")

    return parser.parse_args()


# pylint: disable=too-many-locals
def fetch_active_repositories(api_config, org_name, since_date, repos_to_scan=None):
    """Fetch repositories with PR activity since the given date"""
    logger = logging.getLogger(__name__)

    all_repos = []
    has_next_page = True
    cursor = None

    while has_next_page:
        cursor_arg = f', after: "{cursor}"' if cursor else ""
        query = f"""
        query ($org: String!) {{
            organization(login: $org) {{
                repositories(first: 100{cursor_arg}, orderBy: {{field: PUSHED_AT, direction: DESC}}) {{
                    pageInfo {{
                        hasNextPage
                        endCursor
                    }}
                    nodes {{
                        name
                        pushedAt
                        pullRequests(states: [OPEN, CLOSED, MERGED],
                                    first: 50,  # Increased to get more recent PRs
                                    orderBy: {{field: UPDATED_AT, direction: DESC}}) {{
                            nodes {{
                                updatedAt
                                number
                                createdAt
                            }}
                            totalCount
                        }}
                        defaultBranchRef {{
                            name
                        }}
                    }}
                }}
            }}
        }}
        """

        variables = {"org": org_name}

        try:
            response = requests.post(
                api_config["url"],
                headers=api_config["headers"],
                json={"query": query, "variables": variables},
                timeout=120,
            )
            response.raise_for_status()
            data = response.json()

            if "errors" in data:
                logger.error("GraphQL errors: %s", data["errors"])
                return []

            if "data" not in data or not data["data"]:
                logger.error("No data in response: %s", data)
                return []

            repo_data = data["data"]["organization"]["repositories"]
            repositories = repo_data["nodes"]

            # Add repositories to our collection
            all_repos.extend(repositories)

            # Check pagination
            page_info = repo_data["pageInfo"]
            has_next_page = page_info["hasNextPage"]
            cursor = page_info["endCursor"]

            logger.info("Fetched %d repositories so far...", len(all_repos))

        except Exception as e:
            logger.error("Failed to fetch repository data: %s", str(e))
            return []

    logger.info("Total repositories fetched: %d", len(all_repos))

    # Filter repositories if a specific list is provided
    if repos_to_scan:
        all_repos = [repo for repo in all_repos if repo["name"] in repos_to_scan]
        logger.info("Filtered to %d specific repositories", len(all_repos))

    active_repos = []
    for repo in all_repos:
        if not repo.get("defaultBranchRef"):
            continue

        prs = repo.get("pullRequests", {})
        pr_nodes = prs.get("nodes", [])

        # Check if repository has recent activity (push or PR activity)
        repo_pushed_at = repo.get("pushedAt")
        last_push_date = None
        if repo_pushed_at:
            last_push_date = parse_github_date(repo_pushed_at)

        # Filter PRs by date
        recent_prs = []
        for pr in pr_nodes:
            pr_date = parse_github_date(pr["updatedAt"])
            if pr_date >= since_date:
                recent_prs.append(pr)

        # Include repos with recent pushes OR recent PRs
        has_recent_activity = (last_push_date and last_push_date >= since_date) or len(recent_prs) > 0

        if has_recent_activity:
            # Determine the most recent activity date
            activity_dates = []
            if last_push_date:
                activity_dates.append(last_push_date)
            if recent_prs:
                activity_dates.append(parse_github_date(recent_prs[0]["updatedAt"]))

            last_activity_date = max(activity_dates) if activity_dates else last_push_date

            active_repos.append(
                {
                    "name": repo["name"],
                    "default_branch": repo["defaultBranchRef"]["name"] if repo.get("defaultBranchRef") else "unknown",
                    "last_push_date": last_push_date,
                    "last_pr_date": parse_github_date(recent_prs[0]["updatedAt"]) if recent_prs else None,
                    "last_activity_date": last_activity_date,
                    "recent_pr_count": len(recent_prs),
                    "total_pr_count": prs.get("totalCount", 0),
                }
            )

    return active_repos


def main():
    """Main function to identify active repositories"""
    try:
        args = parse_arguments()
        logger = setup_logging(args.verbose)

        # Get token from environment variable
        token = os.getenv(args.token_env)
        if not token:
            logger.error("Environment variable '%s' is not set or is empty", args.token_env)
            logger.error("Please set it with: export %s=your_github_token", args.token_env)
            sys.exit(1)

        # Validate token format (basic check)
        if not token.startswith(("ghp_", "gho_", "ghu_", "ghs_", "ghr_")):
            logger.warning("Token doesn't appear to be in expected GitHub format (ghp_*, gho_*, etc.)")

        api_config = {
            "url": "https://api.github.com/graphql",
            "headers": {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github.v4+json",
            },
        }

        since_date = datetime.now(timezone.utc) - timedelta(days=args.days)

        logger.info("Fetching repositories with activity since %s (%d days ago)", since_date.date(), args.days)
        logger.info("Organization: %s", args.org)

        active_repos = fetch_active_repositories(api_config, args.org, since_date, None)

        if not active_repos:
            logger.info("No repositories found with activity in the last %d days", args.days)
            return

        # Sort by last push date to match GitHub web interface exactly
        active_repos.sort(key=lambda x: x["last_push_date"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

        logger.info(f"\nRepositories with activity in the last {args.days} days:")
        for repo in active_repos:
            last_push_str = repo["last_push_date"].strftime("%Y-%m-%d") if repo["last_push_date"] else "N/A"
            last_pr_str = repo["last_pr_date"].strftime("%Y-%m-%d") if repo["last_pr_date"] else "N/A"
            logger.info(
                "- %s (last push: %s, last PR: %s, recent PRs: %d, total PRs: %d)",
                repo["name"],
                last_push_str,
                last_pr_str,
                repo["recent_pr_count"],
                repo["total_pr_count"],
            )

        logger.info("\nSummary:")
        logger.info("Total active repositories: %d", len(active_repos))
        logger.info("Organization: %s", args.org)
        logger.info(
            "Time period: %s to %s", since_date.strftime("%Y-%m-%d"), datetime.now(timezone.utc).strftime("%Y-%m-%d")
        )

    except Exception as e:
        logger.error("An error occurred: %s", str(e), exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
