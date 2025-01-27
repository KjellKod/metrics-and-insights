import os
import requests
from datetime import datetime
import argparse
from dotenv import load_dotenv

load_dotenv()

# GitHub API setup
access_token = os.environ.get("GITHUB_TOKEN_READONLY_WEB")
owner = os.environ.get("GITHUB_METRIC_OWNER")
repo = os.environ.get("GITHUB_METRIC_REPO")
base_url = f"https://api.github.com/repos/{owner}/{repo}"
headers = {
    "Authorization": f"token {access_token}",
    "Accept": "application/vnd.github.v3+json",
}


def get_commits_stats(start_date, end_date):
    url = f"{base_url}/commits"
    params = {"sha": "master", "since": start_date.isoformat(), "until": end_date.isoformat(), "per_page": 100}

    total_additions = 0
    total_deletions = 0
    commits_processed = 0

    while True:
        response = requests.get(url, headers=headers, params=params)
        if response.status_code != 200:
            print(f"Failed to fetch commits: {response.status_code}")
            break

        commits = response.json()
        if not commits:
            break

        for commit in commits:
            commit_url = commit["url"]
            commit_response = requests.get(commit_url, headers=headers)
            if commit_response.status_code == 200:
                commit_data = commit_response.json()
                total_additions += commit_data["stats"]["additions"]
                total_deletions += commit_data["stats"]["deletions"]
                commits_processed += 1
                print(
                    f"Processed commit {commits_processed}: +{commit_data['stats']['additions']} -{commit_data['stats']['deletions']}"
                )

        if "next" not in response.links:
            break
        url = response.links["next"]["url"]

    return total_additions, total_deletions, commits_processed


def main():
    parser = argparse.ArgumentParser(description="Analyze lines changed on master branch")
    parser.add_argument("--start-date", type=str, required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, required=True, help="End date (YYYY-MM-DD)")
    args = parser.parse_args()

    start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
    end_date = datetime.strptime(args.end_date, "%Y-%m-%d")

    additions, deletions, commits = get_commits_stats(start_date, end_date)

    print(f"\nAnalysis for period {args.start_date} to {args.end_date}:")
    print(f"Total commits processed: {commits}")
    print(f"Total lines added: {additions}")
    print(f"Total lines deleted: {deletions}")
    print(f"Net change: {additions - deletions}")


if __name__ == "__main__":
    main()
