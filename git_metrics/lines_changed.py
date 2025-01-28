import os
import sys
from datetime import datetime
import argparse
import logging

import requests
from dotenv import load_dotenv


load_dotenv()


def setup_logging():
    """Configure logging settings."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    return logging.getLogger(__name__)


# pylint: disable=broad-exception-caught
def fetch_commit_data(graphql_url, headers, query, variables, timeout=30):
    logger = logging.getLogger(__name__)
    try:
        response = requests.post(
            graphql_url, headers=headers, json={"query": query, "variables": variables}, timeout=timeout
        )
        response.raise_for_status()
        return response.json()
    except requests.Timeout:
        logger.error("Request timed out after %d seconds", timeout)
        return None
    except requests.ConnectionError:
        logger.error("Network connection error occurred")
        return None
    except requests.RequestException as e:
        logger.error("An error occurred while fetching commit data: %s", str(e))
        return None
    except Exception as e:
        logger.error("Unexpected error occurred: %s", str(e), exc_info=True)
        return None


def process_commit_data(commit_history, progress_callback=None):
    total_additions = 0
    total_deletions = 0
    commits_processed = 0

    for commit in commit_history["nodes"]:
        total_additions += commit["additions"]
        total_deletions += commit["deletions"]
        commits_processed += 1

        if progress_callback:
            progress_callback(commits_processed, commit["additions"], commit["deletions"])

    return total_additions, total_deletions, commits_processed


def setup_github_api(access_token):
    """Setup GitHub API configuration."""
    return {
        "url": "https://api.github.com/graphql",
        "headers": {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github.v4+json",
        },
        "query": """
        query ($owner: String!, $repo: String!, $since: GitTimestamp!, $until: GitTimestamp!, $cursor: String) {
            repository(owner: $owner, name: $repo) {
                defaultBranchRef {
                    target {
                        ... on Commit {
                            history(since: $since, until: $until, first: 100, after: $cursor) {
                                pageInfo {
                                    hasNextPage
                                    endCursor
                                }
                                nodes {
                                    additions
                                    deletions
                                }
                            }
                        }
                    }
                }
            }
        }
        """,
    }


def fetch_commit_page(api_config, variables):
    """Fetch a single page of commit data and extract history."""
    data = fetch_commit_data(api_config["url"], api_config["headers"], api_config["query"], variables)
    if not data:
        return None
    return data["data"]["repository"]["defaultBranchRef"]["target"]["history"]


# pylint: disable=broad-exception-caught,too-many-positional-arguments,too-many-arguments,too-many-locals
def get_commits_stats(start_date, end_date, owner, repo, access_token, progress_callback=None):
    """Get commit statistics for the specified period."""
    logger = logging.getLogger(__name__)
    api_config = setup_github_api(access_token)
    total_additions = total_deletions = commits_processed = 0
    cursor = None

    while True:
        variables = {
            "owner": owner,
            "repo": repo,
            "since": start_date.isoformat(),
            "until": end_date.isoformat(),
            "cursor": cursor,
        }

        commit_history = fetch_commit_page(api_config, variables)
        if not commit_history:
            logger.error("Failed to fetch commit data")
            break

        additions, deletions, processed = process_commit_data(commit_history, progress_callback)
        total_additions += additions
        total_deletions += deletions
        commits_processed += processed

        try:
            if not commit_history["pageInfo"]["hasNextPage"]:
                break
            cursor = commit_history["pageInfo"]["endCursor"]
        except (KeyError, TypeError) as e:
            logger.error("Error accessing pagination info: %s", str(e))
            logger.warning("Response structure might be invalid or incomplete")
            break

    return total_additions, total_deletions, commits_processed


def validate_env_variables():
    """Validate required environment variables and return their values."""
    logger = logging.getLogger(__name__)
    required_vars = {
        "GITHUB_TOKEN_READONLY_WEB": "GitHub access token",
        "GITHUB_METRIC_OWNER": "GitHub repository owner",
        "GITHUB_METRIC_REPO": "GitHub repository name",
    }

    missing_vars = []
    env_values = {}

    for var, description in required_vars.items():
        value = os.environ.get(var)
        if not value:
            missing_vars.append(f"{var} ({description})")
        env_values[var] = value

    if missing_vars:
        logger.error("Missing required environment variables:\n%s", "\n".join(f"- {var}" for var in missing_vars))
        raise ValueError("Missing required environment variables")

    return env_values


def parse_arguments():
    """Parse and validate command line arguments."""
    parser = argparse.ArgumentParser(description="Analyze lines changed on master branch")
    parser.add_argument("--start-date", type=str, required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, required=True, help="End date (YYYY-MM-DD)")
    return parser.parse_args()


def main():
    logger = setup_logging()
    try:
        args = parse_arguments()
        env_vars = validate_env_variables()

        start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d")

        def log_progress(commits_processed, additions, deletions):
            logger.info("Processed commit %d: +%d -%d", commits_processed, additions, deletions)

        additions, deletions, commits = get_commits_stats(
            start_date,
            end_date,
            env_vars["GITHUB_METRIC_OWNER"],
            env_vars["GITHUB_METRIC_REPO"],
            env_vars["GITHUB_TOKEN_READONLY_WEB"],
            progress_callback=log_progress,
        )

        logger.info("\nAnalysis for period %s to %s:", args.start_date, args.end_date)
        logger.info("Total commits processed: %d", commits)
        logger.info("Total lines added: %d", additions)
        logger.info("Total lines deleted: %d", deletions)
        logger.info("Net change: %d", additions - deletions)

    except ValueError as e:
        logger.error("Configuration error: %s", str(e))
        sys.exit(1)
    except Exception as e:
        logger.error("An error occurred: %s", str(e), exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
