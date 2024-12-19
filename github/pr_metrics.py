import os
import requests
import statistics
from collections import defaultdict
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Global variable for verbosity
VERBOSE = False


def verbose_print(message):
    if VERBOSE:
        print(message)


def get_common_parser():
    # pylint: disable=global-statement
    # Define the argument parser
    parser = argparse.ArgumentParser(description="Common script options")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output")
    parser.add_argument("-csv", action="store_true", help="Export the release data to a CSV file.")

    return parser


def parse_common_arguments(parser=None):
    if parser is None:
        parser = get_common_parser()
    global VERBOSE
    args = parser.parse_args()
    VERBOSE = args.verbose
    print(f"Verbose printing enabled: {VERBOSE}")
    return parser.parse_args()


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


# def get_pull_requests(start_date, state="closed", per_page=100):
#     url = f"{base_url}/pulls"
#     start_date = datetime.strptime(start_date, "%Y-%m-%dT%H:%M:%SZ")
#     params = {"state": state, "per_page": per_page, "sort": "updated", "direction": "desc"}
#     prs = []
#     if start_date is None:
#         start_date = "2024-07-01T00:00:00Z"

#     while url:
#         response = requests.get(url, headers=headers, params=params)
#         page_prs = response.json()
#         for pr in page_prs:
#             if pr["merged_at"]:
#                 merged_at = datetime.strptime(pr["merged_at"], "%Y-%m-%dT%H:%M:%SZ")
#                 if merged_at > start_date:
#                     prs.append(pr)
#                 elif merged_at < start_date:
#                     print
#                     return prs  # We've gone past 2024, so we can stop
#         url = response.links.get("next", {}).get("url")
#     return prs


def get_pull_requests(start_date, state="closed", per_page=100):
    url = f"{base_url}/pulls"
    start_date = datetime.strptime(start_date, "%Y-%m-%dT%H:%M:%SZ")
    params = {
        "state": state,
        "per_page": per_page,
        "sort": "created",
        "direction": "desc",
        "since": "2024-01-01T00:00:00Z",
    }  # Fetch PRs updated after this date}

    prs = []

    abort_count = 0
    max_old_before_abort = 100
    while url:
        if abort_count >= max_old_before_abort:
            print(f"Aborting main retrieval after {abort_count} consecutive old PRs")
            break

        response = requests.get(url, headers=headers, params=params)
        if response.status_code != 200:
            print(f"Failed to fetch PRs: {response.status_code}")
            break

        page_prs = response.json()
        for pr in page_prs:
            if abort_count >= max_old_before_abort:
                break
            if pr["merged_at"]:
                merged_at = datetime.strptime(pr["merged_at"], "%Y-%m-%dT%H:%M:%SZ")
                if merged_at >= start_date:
                    abort_count = 0
                    print(f"Adding PR: {pr['number']}, Merged at: {merged_at}, Start date: {start_date}")
                    prs.append(pr)
                elif merged_at < start_date:
                    abort_count += 1
                    print(f"Ignoring PR: {pr['number']}, Merged at: {merged_at}, Start date: {start_date}")
                # Do not break here; continue fetching all pages
        url = response.links.get("next", {}).get("url")

    # Sort PRs by merged_at in descending order
    prs.sort(key=lambda pr: datetime.strptime(pr["merged_at"], "%Y-%m-%dT%H:%M:%SZ"), reverse=True)

    print(f"Total PRs fetched: {len(prs)}")
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
                verbose_print(f"Found {len(data['check_runs'])} check runs for commit {commit['sha']}")
            all_check_runs.extend(data.get("check_runs", []))
            url = response.links.get("next", {}).get("url")
    return all_check_runs


def calculate_metrics(prs):
    pr_metrics = defaultdict(list)

    print(f"Processing {len(prs)} PRs")
    for pr in prs:
        pr_number = pr["number"]
        print(f"Processing PR #{pr_number}")

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
        total_check_time_seconds = 0
        verbose_print(f"\nChecks for PR #{pr_number}:")
        for check in check_runs:
            started_at = datetime.strptime(check["started_at"], "%Y-%m-%dT%H:%M:%SZ")
            completed_at = datetime.strptime(check["completed_at"], "%Y-%m-%dT%H:%M:%SZ")
            check_duration = (completed_at - started_at).total_seconds()
            total_check_time_seconds += check_duration
            verbose_print(f"Check {check['name']} took {check_duration} seconds")

        pr_metrics[merge_month].append(
            {
                "pr_number": pr_number,
                "merge_time": merge_time.total_seconds(),
                "total_check_time": total_check_time_seconds,
            }
        )

    return pr_metrics


def print_metrics(pr_metrics):
    # for month, prs in sorted(pr_metrics.items()):
    #     print("Month, Median Merge Time (hours), Median Check Time (minutes), Check Time (m) / Merge Time Ratio (m)")
    #     print(f"Total PRs merged: {len(prs)}")
    #     merge_times = [pr["merge_time"] for pr in prs]
    #     check_times = [pr["total_check_time"] for pr in prs]

    #     median_merge_time = statistics.median(merge_times)  # / 3600  # converted to hours
    #     median_check_time = statistics.median(check_times)  # / 60  # converted to minutes
    #     # ratio = (median_check_time / 60) / median_merge_time  # Convert check time to hours for ratio
    #     print(f"{month}, {median_merge_time:.2f}, {median_check_time:.2f}")

    #     # Merge/check time are in minutes
    #     ratio_percentage = (median_check_time) / median_merge_time * 60 * 100
    #     print(f"{month}, {median_merge_time/3600:.2f}, {median_check_time/60:.2f}, {ratio_percentage:.2f}")

    # print("\n\n")
    print("Month, Total PRs, Median Merge Time (hours), Median Check Time (minutes), Check Time / Merge Time Ratio (%)")
    for month, prs in sorted(pr_metrics.items()):
        merge_times = [pr["merge_time"] for pr in prs]
        check_times = [pr["total_check_time"] for pr in prs]

        median_merge_time = statistics.median(merge_times)  # Already in seconds
        median_check_time = statistics.median(check_times)  # Already in seconds

        # Convert to appropriate units for display
        median_merge_time_hours = median_merge_time / 3600  # Convert to hours
        median_check_time_minutes = median_check_time / 60  # Convert to minutes

        # Calculate ratio percentage
        ratio_percentage = (median_check_time / median_merge_time) * 100

        print(
            f"{month}, {len(prs)}, {median_merge_time_hours:.2f}, {median_check_time_minutes:.2f}, {ratio_percentage:.2f}"
        )


# following UTC time format although it's possible that the CI was running in a different timezone
def main():
    start_date = "2024-07-01T00:00:00Z"  # we changed the CI roughly around here so this is a good starting point
    parse_common_arguments
    prs = get_pull_requests(start_date, state="closed", per_page=100)  # get_single_pull_request("5051")
    metrics = calculate_metrics(prs)

    for month, pr_data in metrics.items():
        print(f"\nMetrics for {month}:")
        for data in pr_data:
            print(
                f"PR #{data['pr_number']}: Merge Time: {data['merge_time']/3600:.2f} hours, Total Check Time: {data['total_check_time']/60:.2f} minutes"
            )

    print_metrics(metrics)


if __name__ == "__main__":
    main()
