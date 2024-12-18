import os
import requests
import json
from datetime import datetime
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

# GitHub API setup
access_token = os.environ.get("GITHUB_TOKEN_READONLY_WEB")
owner = "onfleet"
repo = "web"
base_url = f"https://api.github.com/repos/{owner}/{repo}"
headers = {
    "Authorization": f"token {access_token}",
    "Accept": "application/vnd.github.v3+json",
}


def get_single_pull_request(pr_number):
    url = f"{base_url}/pulls/{pr_number}"
    response = requests.get(url, headers=headers)
    return [response.json()] if response.status_code == 200 else []


def get_pull_requests(state="closed", per_page=100):
    url = f"{base_url}/pulls"
    params = {"state": state, "per_page": per_page, "sort": "updated", "direction": "desc"}
    prs = []
    while url:
        response = requests.get(url, headers=headers, params=params)
        page_prs = response.json()
        for pr in page_prs:
            if pr["merged_at"]:
                merged_at = datetime.strptime(pr["merged_at"], "%Y-%m-%dT%H:%M:%SZ")
                if merged_at.year == 2024:
                    prs.append(pr)
                elif merged_at.year < 2024:
                    return prs  # We've gone past 2024, so we can stop
        url = response.links.get("next", {}).get("url")
    return prs


def get_pr_reviews(pr_number):
    url = f"{base_url}/pulls/{pr_number}/reviews"
    response = requests.get(url, headers=headers)
    return response.json()


def is_pr_approved(reviews):
    return any(review["state"] == "APPROVED" for review in reviews)


def get_pr_commits(pr_number):
    url = f"{base_url}/pulls/{pr_number}/commits"
    commits = []
    while url:
        response = requests.get(url, headers=headers)
        commits.extend(response.json())
        url = response.links.get("next", {}).get("url")
    return commits


def get_check_runs(pr_number):
    commits = get_pr_commits(pr_number)
    all_check_runs = []
    for commit in commits:
        url = f"{base_url}/commits/{commit['sha']}/check-runs"
        while url:
            response = requests.get(url, headers=headers)
            if response.status_code != 200:
                print(f"Failed to fetch check runs for commit {commit['sha']}: {response.status_code}")
                break
            data = response.json()
            if "check_runs" not in data:
                print(f"No check runs found for commit {commit['sha']}")
            else:
                print(f"Found {len(data['check_runs'])} check runs for commit {commit['sha']}")
            all_check_runs.extend(data.get("check_runs", []))
            url = response.links.get("next", {}).get("url")
    return all_check_runs


def calculate_metrics(prs):
    pr_metrics = defaultdict(list)

    for pr in prs:
        pr_number = pr["number"]

        if not pr or pr.get("state") != "closed" or not pr.get("merged_at"):
            print(f"PR #{pr_number} not found, not closed, or not merged.")
            continue

        reviews = get_pr_reviews(pr_number)

        if not is_pr_approved(reviews):
            print(f"PR #{pr_number} was not approved.")
            continue

        created_at = datetime.strptime(pr["created_at"], "%Y-%m-%dT%H:%M:%SZ")
        merged_at = datetime.strptime(pr["merged_at"], "%Y-%m-%dT%H:%M:%SZ")

        merge_time = merged_at - created_at
        merge_month = merged_at.strftime("%Y-%m")

        # Get check runs for this PR
        check_runs = get_check_runs(pr_number)

        # Calculate total time spent on status checks
        total_check_time = 0
        print(f"\nChecks for PR #{pr_number}:")
        for check in check_runs:
            started_at = datetime.strptime(check["started_at"], "%Y-%m-%dT%H:%M:%SZ")
            completed_at = datetime.strptime(check["completed_at"], "%Y-%m-%dT%H:%M:%SZ")
            check_duration = (completed_at - started_at).total_seconds()
            total_check_time += check_duration
            print(f"Check {check['name']} took {check_duration} seconds")

        pr_metrics[merge_month].append(
            {"pr_number": pr_number, "merge_time": merge_time.total_seconds(), "total_check_time": total_check_time}
        )

    return pr_metrics


def print_metrics(pr_metrics):
    for month, prs in sorted(pr_metrics.items()):
        print(f"\nMonth: {month}")
        print(f"Total PRs merged: {len(prs)}")
        avg_merge_time_hours = sum(pr["merge_time_hours"] for pr in prs) / len(prs)
        avg_check_time_hours = sum(pr["total_check_time_minutes"] / 60 for pr in prs) / len(prs)
        avg_check_time_percentage = sum(pr["total_check_time_percentage"] for pr in prs) / len(prs)
        print(f"Average merge time: {avg_merge_time_hours:.2f} hours")
        print(
            f"Average time spent on checks: {avg_check_time_hours:.2f} hours ({avg_check_time_percentage:.2f}% of merge time)"
        )

        for pr in prs:
            print(f"  PR #{pr['pr_number']}: Merged after {pr['merge_time_hours']:.2f} hours")
            print(
                f"    Time on checks: {pr['total_check_time_minutes'] / 60:.2f} hours ({pr['total_check_time_percentage']:.2f}% of merge time)"
            )


def main():
    prs = get_single_pull_request("5051")  # get_pull_requests(state="closed", per_page=100)
    metrics = calculate_metrics(prs)

    for month, pr_data in metrics.items():
        print(f"\nMetrics for {month}:")
        for data in pr_data:
            print(
                f"PR #{data['pr_number']}: Merge Time: {data['merge_time']/3600:.2f} hours, Total Check Time: {data['total_check_time']/60:.2f} minutes"
            )


if __name__ == "__main__":
    main()
