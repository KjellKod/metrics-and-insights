import os
import requests
from datetime import datetime
import argparse
from dotenv import load_dotenv

load_dotenv()


def fetch_commit_data(graphql_url, headers, query, variables, timeout=30):
    try:
        response = requests.post(
            graphql_url, headers=headers, json={"query": query, "variables": variables}, timeout=timeout
        )
        response.raise_for_status()  # Raises an HTTPError for bad responses (4xx, 5xx)
        return response.json()
    except requests.Timeout:
        print(f"Request timed out after {timeout} seconds")
        return None
    except requests.ConnectionError:
        print("Network connection error occurred")
        return None
    except requests.RequestException as e:
        print(f"An error occurred while fetching commit data: {str(e)}")
        return None
    except Exception as e:
        print(f"Unexpected error occurred: {str(e)}")
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


def get_commits_stats(start_date, end_date, owner, repo, access_token, progress_callback=None):
    """Get commit statistics for the specified period."""
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
            print("Failed to fetch commit data")
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
            print(f"Error accessing pagination info: {str(e)}")
            print("Response structure might be invalid or incomplete")
            break

    return total_additions, total_deletions, commits_processed


def validate_env_variables():
    """Validate required environment variables and return their values."""
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
        raise ValueError("Missing required environment variables:\n" + "\n".join(f"- {var}" for var in missing_vars))

    return env_values


def main():
    parser = argparse.ArgumentParser(description="Analyze lines changed on master branch")
    parser.add_argument("--start-date", type=str, required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, required=True, help="End date (YYYY-MM-DD)")
    args = parser.parse_args()

    try:
        # Validate environment variables first
        env_vars = validate_env_variables()

        start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d")

        def log_progress(commits_processed, additions, deletions):
            print(f"Processed commit {commits_processed}: +{additions} -{deletions}")

        additions, deletions, commits = get_commits_stats(
            start_date,
            end_date,
            env_vars["GITHUB_METRIC_OWNER"],
            env_vars["GITHUB_METRIC_REPO"],
            env_vars["GITHUB_TOKEN_READONLY_WEB"],
            progress_callback=log_progress,
        )

        print(f"\nAnalysis for period {args.start_date} to {args.end_date}:")
        print(f"Total commits processed: {commits}")
        print(f"Total lines added: {additions}")
        print(f"Total lines deleted: {deletions}")
        print(f"Net change: {additions - deletions}")

    except ValueError as e:
        print(f"Configuration error: {str(e)}")
        sys.exit(1)
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
