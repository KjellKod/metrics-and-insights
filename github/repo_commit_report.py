"""
Repository Commit Report Generator

This script generates a detailed commit report for specified GitHub repositories between two dates.
It fetches commit information including hashes, authors, dates, and messages, outputting them to a CSV file.
Focuses specifically on merge commits from pull requests to the main/master branch.

Features:
- Fetches merge commits between specified dates for multiple repositories
- Handles GitHub API pagination for large commit histories
- Generates a CSV report with commit details
- Includes error handling and reporting
- Uses environment variables for GitHub authentication

Required Environment Variables:
    GITHUB_TOKEN_READONLY_WEB: GitHub API token with repository read access

Usage:
    python repo_commit_report.py --start-date YYYY-MM-DD --end-date YYYY-MM-DD --repos "owner1/repo1,owner2/repo2"
    python repo_commit_report.py --start-date YYYY-MM-DD --end-date YYYY-MM-DD --config repos.json

Example JSON config file (repos.json):
{
    "repositories": [
        {"owner": "owner1", "repo": "repo1"},
        {"owner": "owner2", "repo": "repo2"}
    ]
}
"""

import os
import sys
import argparse
from datetime import datetime
import csv
import json
import requests
from typing import List, Dict
from dotenv import load_dotenv

load_dotenv()


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Generate a GitHub repository commit report between two dates",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    Basic usage:
    $ python repo_commit_report.py --start-date 10/15/2024 --end-date 1/15/2025 --repos "owner1/repo1,owner2/repo2"

    Using config file:
    $ python repo_commit_report.py --start-date 2024-01-15 --end-date 2024-02-15 --config repos.json

    Note: Repositories must be in owner/repo format and comma-separated without spaces:
    CORRECT: "owner1/repo1,owner2/repo2"
    INCORRECT: "repo1,repo2" or "owner1/repo1, owner2/repo2"
    """,
    )

    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)

    parser.add_argument(
        "--start-date", required=True, help="Start date (accepted formats: YYYY-MM-DD, YYYY/MM/DD, MM/DD/YYYY)"
    )
    parser.add_argument(
        "--end-date", required=True, help="End date (accepted formats: YYYY-MM-DD, YYYY/MM/DD, MM/DD/YYYY)"
    )

    repo_source = parser.add_mutually_exclusive_group(required=True)
    repo_source.add_argument(
        "--repos", help="Comma-separated list of repositories in owner/repo format (e.g., 'owner1/repo1,owner2/repo2')"
    )
    repo_source.add_argument("--config", help="Path to JSON configuration file containing repository list")

    # Check for common dash/hyphen errors
    for arg in sys.argv:
        if arg.startswith("–"):  # Check for en-dash
            print("\nError: Invalid dash character detected in argument:", arg)
            print("Make sure to use regular hyphens (--) instead of en-dashes (–)")
            print("\nCorrect usage example:")
            print('python3 repo_commit_report.py --start-date 10/15/2024 --end-date 1/15/2025 --repos "owner/repo"')
            sys.exit(1)

    return parser.parse_args()


def validate_date(date_string: str) -> datetime:
    """
    Validates and converts date string to datetime object.
    Accepts multiple date formats.
    """
    date_formats = [
        "%Y-%m-%d",  # YYYY-MM-DD
        "%Y/%m/%d",  # YYYY/MM/DD
        "%m/%d/%Y",  # MM/DD/YYYY
        "%m-%d-%Y",  # MM-DD-YYYY
    ]

    for date_format in date_formats:
        try:
            return datetime.strptime(date_string, date_format)
        except ValueError:
            continue

    return None


def get_commits(owner: str, repo: str, start_date: str, end_date: str, access_token: str) -> Dict:
    """
    Fetches commits from GitHub API for a specific repository and date range.
    Only includes commits that were merged to master/main branch.
    """
    try:
        # First, get the default branch name
        repo_url = f"https://api.github.com/repos/{owner}/{repo}"
        headers = {
            "Authorization": f"token {access_token}",
            "Accept": "application/vnd.github.v3+json",
        }

        print(f"\nChecking repository: {repo_url}")
        repo_response = requests.get(repo_url, headers=headers)

        if repo_response.status_code != 200:
            error_msg = f"Failed to get repo info. Status: {repo_response.status_code}, Response: {repo_response.text}"
            print(error_msg)
            return {"status": "error", "message": error_msg}

        repo_data = repo_response.json()
        default_branch = repo_data["default_branch"]
        print(f"Default branch: {default_branch}")

        # Now get commits
        commits_url = f"{repo_url}/commits"
        params = {
            "since": f"{start_date}T00:00:00Z",
            "until": f"{end_date}T23:59:59Z",
            "sha": default_branch,
            "per_page": 100,
        }

        print(f"Fetching commits from {commits_url}")
        print(f"Parameters: {params}")

        all_commits = []
        merge_commits = []
        while commits_url:
            response = requests.get(commits_url, headers=headers, params=params)

            if response.status_code != 200:
                error_msg = f"Failed to get commits. Status: {response.status_code}, Response: {response.text}"
                print(error_msg)
                return {"status": "error", "message": error_msg}

            page_commits = response.json()
            all_commits.extend(page_commits)
            print(f"Retrieved {len(page_commits)} commits from current page")

            for commit in page_commits:
                commit_message = commit.get("commit", {}).get("message", "")
                parents = commit.get("parents", [])

                if commit_message.startswith("Merge pull request") and len(parents) > 1:
                    merge_commits.append(commit)
                    print(f"Found merge commit: {commit_message.split('\n')[0]}")

            # Check for pagination
            commits_url = response.links.get("next", {}).get("url")
            params = {}  # Clear params after first request

            if commits_url:
                print(f"Found next page: {commits_url}")

        print(f"\nSummary:")
        print(f"Total commits found: {len(all_commits)}")
        print(f"Merge commits found: {len(merge_commits)}")

        if len(merge_commits) == 0:
            print("\nNo merge commits found. This could mean:")
            print("1. No PRs were merged in this date range")
            print("2. PRs were merged using a different method (squash/rebase)")
            print("3. The commit messages don't follow the 'Merge pull request' pattern")

            # Sample of commit messages to help debug
            print("\nSample of commit messages found:")
            for commit in all_commits[:5]:
                print(f"- {commit['commit']['message'].split('\n')[0]}")

        return {"status": "success", "data": merge_commits}

    except requests.RequestException as e:
        error_msg = f"Request failed: {str(e)}"
        print(error_msg)
        return {"status": "error", "message": error_msg}
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        print(error_msg)
        return {"status": "error", "message": error_msg}


def parse_repo_string(repos_str: str) -> List[Dict[str, str]]:
    """
    Parse comma-separated repository string into list of repository dictionaries.
    """
    repositories = []
    repo_list = [repo.strip() for repo in repos_str.split(",")]

    for repo in repo_list:
        if not repo:
            continue

        try:
            if "/" not in repo:
                print(f"Error: Invalid repository format '{repo}'. Must be 'owner/repo'")
                continue

            owner, repo_name = repo.split("/")
            owner = owner.strip()
            repo_name = repo_name.strip()

            if not owner or not repo_name:
                print(f"Error: Invalid repository format '{repo}'. Both owner and repo name must be provided")
                continue

            repositories.append({"owner": owner, "repo": repo_name})
        except ValueError:
            print(f"Error: Invalid repository format '{repo}'. Must be 'owner/repo'")
            continue

    if not repositories:
        print("\nNo valid repositories found. Repository format must be 'owner/repo'")
        print('Example: --repos "owner1/repo1,owner2/repo2"')
        sys.exit(1)

    return repositories


def load_config_file(config_path: str) -> List[Dict[str, str]]:
    """
    Load repository configuration from JSON file.
    """
    try:
        with open(config_path, "r") as f:
            config = json.load(f)
            if not isinstance(config.get("repositories"), list):
                raise ValueError("Config file must contain 'repositories' list")
            return config["repositories"]
    except (json.JSONDecodeError, FileNotFoundError, KeyError) as e:
        print(f"Error loading config file: {str(e)}")
        return []


def process_repository(repo_info: Dict[str, str], start_date: str, end_date: str, access_token: str) -> List[Dict]:
    """
    Process a single repository to get commit information.
    Only includes PR merge commits.
    """
    owner = repo_info["owner"]
    repo = repo_info["repo"]
    print(f"\nProcessing repository: {owner}/{repo}")

    result = get_commits(owner, repo, start_date, end_date, access_token)

    if result["status"] == "success":
        commits = result["data"]
        if not commits:
            print("No merge commits found in the specified date range")
            return [
                {
                    "repository": f"{owner}/{repo}",
                    "status": "success",
                    "hash": "",
                    "author": "",
                    "date": "",
                    "message": "No merge commits found in the specified date range",
                    "pr_number": "",
                    "error": "",
                }
            ]

        processed_commits = []
        print(f"Processing {len(commits)} commits...")

        for commit in commits:
            commit_message = commit["commit"]["message"]
            # Only include PR merge commits
            if commit_message.startswith("Merge pull request"):
                try:
                    # Try to extract PR number from merge commit message
                    pr_number = commit_message.split()[3].replace("#", "")
                    processed_commits.append(
                        {
                            "repository": f"{owner}/{repo}",
                            "status": "success",
                            "hash": commit["sha"][:7],
                            "author": commit["commit"]["author"]["name"],
                            "date": commit["commit"]["author"]["date"],
                            "message": commit_message.replace("\n", " "),
                            "pr_number": pr_number,
                            "error": "",
                        }
                    )
                    print(f"Processed PR #{pr_number} - {commit['sha'][:7]}")
                except (IndexError, AttributeError) as e:
                    print(f"Warning: Could not parse PR number from commit {commit['sha'][:7]}: {str(e)}")
                    processed_commits.append(
                        {
                            "repository": f"{owner}/{repo}",
                            "status": "success",
                            "hash": commit["sha"][:7],
                            "author": commit["commit"]["author"]["name"],
                            "date": commit["commit"]["author"]["date"],
                            "message": commit_message.replace("\n", " "),
                            "pr_number": "unknown",
                            "error": f"Could not parse PR number: {str(e)}",
                        }
                    )

        return processed_commits
    else:
        error_result = [
            {
                "repository": f"{owner}/{repo}",
                "status": "error",
                "hash": "",
                "author": "",
                "date": "",
                "message": "",
                "pr_number": "",
                "error": result["message"],
            }
        ]
        print(f"Error processing repository: {result['message']}")
        return error_result


def main():
    try:
        access_token = os.environ.get("GITHUB_TOKEN_READONLY_WEB")
        if not access_token:
            print("\nError: GitHub token not found in environment variables")
            print("Please set GITHUB_TOKEN_READONLY_WEB environment variable")
            print("\nUsage:")
            parse_arguments()
            return

        args = parse_arguments()

        print(f"\nValidating dates...")
        start_date = validate_date(args.start_date)
        end_date = validate_date(args.end_date)

        if not start_date or not end_date:
            print("\nError: Invalid date format")
            print("Accepted formats: YYYY-MM-DD, YYYY/MM/DD, MM/DD/YYYY")
            return

        if start_date > end_date:
            print("\nError: Start date must be before end date")
            return

        print(f"\nDate range: {start_date} to {end_date}")

        repositories = parse_repo_string(args.repos) if args.repos else load_config_file(args.config)

        if not repositories:
            print("\nError: No valid repositories specified")
            print("\nUsage:")
            parse_arguments()
            return

        print(f"\nProcessing {len(repositories)} repositories:")
        for repo in repositories:
            print(f"  - {repo['owner']}/{repo['repo']}")

        all_results = []
        for repo_info in repositories:
            results = process_repository(
                repo_info, start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"), access_token
            )
            all_results.extend(results)

        output_file = "commit_report.csv"
        fieldnames = ["repository", "status", "hash", "author", "date", "message", "pr_number", "error"]

        with open(output_file, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_results)

        print(f"\nReport generated: {output_file}")
        print(f"Total entries: {len(all_results)}")

    except Exception as e:
        print(f"\nError: {str(e)}")
        print("\nUsage:")
        parse_arguments()
        return


if __name__ == "__main__":
    main()
