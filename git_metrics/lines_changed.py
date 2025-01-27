import os
import requests
from datetime import datetime
import argparse
from dotenv import load_dotenv

load_dotenv()


def fetch_commit_data(graphql_url, headers, query, variables):
    response = requests.post(graphql_url, headers=headers, json={"query": query, "variables": variables})
    if response.status_code != 200:
        print(f"Failed to fetch commits: {response.status_code}")
        return None
    return response.json()


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


def get_commits_stats(start_date, end_date, owner, repo, access_token, progress_callback=None):
    graphql_url = "https://api.github.com/graphql"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github.v4+json",
    }
    query = """
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
    """

    total_additions = 0
    total_deletions = 0
    commits_processed = 0
    cursor = None

    while True:
        variables = {
            "owner": owner,
            "repo": repo,
            "since": start_date.isoformat(),
            "until": end_date.isoformat(),
            "cursor": cursor,
        }

        data = fetch_commit_data(graphql_url, headers, query, variables)
        if not data:
            break

        commit_history = data["data"]["repository"]["defaultBranchRef"]["target"]["history"]
        additions, deletions, processed = process_commit_data(commit_history, progress_callback)
        total_additions += additions
        total_deletions += deletions
        commits_processed += processed

        if not commit_history["pageInfo"]["hasNextPage"]:
            break

        cursor = commit_history["pageInfo"]["endCursor"]

    return total_additions, total_deletions, commits_processed


def main():

    parser = argparse.ArgumentParser(description="Analyze lines changed on master branch")
    parser.add_argument("--start-date", type=str, required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, required=True, help="End date (YYYY-MM-DD)")
    args = parser.parse_args()

    # GitHub API setup
    access_token = os.environ.get("GITHUB_TOKEN_READONLY_WEB")
    owner = os.environ.get("GITHUB_METRIC_OWNER")
    repo = os.environ.get("GITHUB_METRIC_REPO")

    start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
    end_date = datetime.strptime(args.end_date, "%Y-%m-%d")

    def log_progress(commits_processed, additions, deletions):
        print(f"Processed commit {commits_processed}: +{additions} -{deletions}")

    additions, deletions, commits = get_commits_stats(
        start_date, end_date, owner, repo, access_token, progress_callback=log_progress
    )

    print(f"\nAnalysis for period {args.start_date} to {args.end_date}:")
    print(f"Total commits processed: {commits}")
    print(f"Total lines added: {additions}")
    print(f"Total lines deleted: {deletions}")
    print(f"Net change: {additions - deletions}")


if __name__ == "__main__":
    main()
