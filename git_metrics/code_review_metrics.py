# pylint: disable=missing-timeout
import argparse
import csv
import os
import re
import sys
from datetime import datetime
import requests
from dotenv import load_dotenv

load_dotenv()

# ========== CONFIGURATION ========== #
GITHUB_API_URL = "https://api.github.com"
TOKEN = os.environ.get("GITHUB_TOKEN_READONLY_WEB", os.environ.get("GITHUB_TOKEN"))

HEADERS = {
    "Authorization": f"token {TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}


# ========== HELPERS ========== #
def iso_to_datetime(iso_str):
    """Convert ISO format string to datetime object."""
    if not iso_str:
        return None
    try:
        return datetime.strptime(iso_str, "%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        return None


# Additional defense-in-depth validation for user-provided repository input
def validate_repo_format(repo):
    """Validate GitHub repo input strictly as owner/repo.

    This prevents path traversal and protocol tricks when composing the request URL
    even though the base host is fixed. Returns the repo if valid, else raises.
    """
    if not isinstance(repo, str):
        raise ValueError("Repository must be a string like 'owner/repo'.")

    # Basic owner/repo shape with allowed GitHub characters
    pattern = r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$"
    if not re.match(pattern, repo):
        raise ValueError("Expected format 'owner/repo' using letters, numbers, '.', '_' or '-'.")

    # Disallow common traversal or protocol-esque characters
    if ".." in repo or repo.startswith("/") or repo.endswith("/") or " " in repo:
        raise ValueError("Repository contains invalid characters or path traversal attempts.")

    return repo

# ========== FETCH PULL REQUESTS ========== #
def fetch_pull_requests(repo, state="closed", per_page=100):
    """Fetch all pull requests with pagination."""
    all_prs = []
    page = 1

    while True:
        url = f"{GITHUB_API_URL}/repos/{repo}/pulls"
        params = {"state": state, "per_page": per_page, "page": page}

        print(f"Fetching page {page} of pull requests...")
        try:
            response = requests.get(url, headers=HEADERS, params=params, timeout=30)
            response.raise_for_status()

            prs = response.json()
            if not prs:
                break

            all_prs.extend(prs)
            print(f"Retrieved {len(prs)} PRs from page {page}")

            page += 1

            # Safer check for next page in Link header
            if "Link" in response.headers and 'rel="next"' in response.headers["Link"]:
                continue
            break
        except requests.RequestException as e:
            print(f"Error fetching PRs: {e}")
            break

    print(f"Total PRs fetched: {len(all_prs)}")
    return all_prs


# ========== FETCH PR REVIEWS ========== #
def fetch_reviews(repo, pr_number):
    """Fetch all reviews for a pull request."""
    url = f"{GITHUB_API_URL}/repos/{repo}/pulls/{pr_number}/reviews"
    all_reviews = []
    page = 1

    while True:
        params = {"per_page": 100, "page": page}
        try:
            response = requests.get(url, headers=HEADERS, params=params, timeout=30)
            response.raise_for_status()

            reviews = response.json()
            if not reviews:
                break

            all_reviews.extend(reviews)
            page += 1

            # Safer check for next page
            if "Link" in response.headers and 'rel="next"' in response.headers["Link"]:
                continue
            break
        except requests.RequestException as e:
            print(f"Error fetching reviews for PR #{pr_number}: {e}")
            break

    return all_reviews


# ========== FETCH PR TIMELINE EVENTS ========== #
def fetch_timeline(repo, pr_number):
    """Fetch timeline events for a pull request."""
    url = f"{GITHUB_API_URL}/repos/{repo}/issues/{pr_number}/timeline"
    all_events = []
    page = 1

    # Timeline API requires a specific preview header
    timeline_headers = HEADERS.copy()
    timeline_headers["Accept"] = "application/vnd.github.mockingbird-preview+json"

    while True:
        params = {"per_page": 100, "page": page}
        try:
            response = requests.get(url, headers=timeline_headers, params=params, timeout=30)
            response.raise_for_status()

            events = response.json()
            if not events:
                break

            all_events.extend(events)
            page += 1

            # Safer check for next page
            if "Link" in response.headers and 'rel="next"' in response.headers["Link"]:
                continue
            break
        except requests.RequestException as e:
            print(f"Error fetching timeline for PR #{pr_number}: {e}")
            break

    return all_events


# ========== PROCESS PR DATA ========== #
def process_pr(repo, pr):
    """Process a pull request and calculate review metrics."""
    try:
        pr_number = pr.get("number")
        if not pr_number:
            raise ValueError("Missing PR number")

        created_at = iso_to_datetime(pr.get("created_at"))
        merged_at = iso_to_datetime(pr.get("merged_at"))

        # If PR wasn't merged, only include basic info
        if not merged_at:
            return [
                pr_number,
                created_at.strftime("%Y-%m-%d %H:%M:%S") if created_at else None,
                None,  # merged_at
                None,  # time_to_merge
                None,  # first_review_start
                None,  # time_to_first_review
                None,  # time_to_first_approval
                None,  # time_from_approval_to_merge
            ]

        # Fetch reviews (more reliable for approval status)
        reviews = fetch_reviews(repo, pr_number)

        # Get timeline events for review requests
        timeline = fetch_timeline(repo, pr_number)

        # Track review request times
        review_requested_times = {}
        for event in timeline:
            if event.get("event") == "review_requested":
                requested_reviewer = event.get("requested_reviewer", {})
                actor = requested_reviewer.get("login") if requested_reviewer else None
                if actor:
                    event_time = iso_to_datetime(event.get("created_at"))
                    if event_time:
                        review_requested_times[actor] = event_time

        # Process review times and approvals
        first_review_time = None
        approval_time = None

        for review in sorted(reviews, key=lambda r: r.get("submitted_at", "")):
            review_time = iso_to_datetime(review.get("submitted_at"))
            if not review_time:
                continue

            reviewer = review.get("user", {}).get("login")
            if not reviewer:
                continue

            # Track first review
            if not first_review_time:
                first_review_time = review_time

            # Track first approval
            if review.get("state") == "APPROVED" and not approval_time:
                approval_time = review_time

        # Calculate metrics
        time_to_merge = None
        time_to_first_review = None
        time_to_first_approval = None
        time_from_approval_to_merge = None
        first_review_start = None

        if merged_at and created_at:
            time_to_merge = round((merged_at - created_at).total_seconds() / 3600, 2)

        if first_review_time:
            first_review_start = first_review_time.strftime("%Y-%m-%d %H:%M:%S")
            if created_at:
                time_to_first_review = round((first_review_time - created_at).total_seconds() / 3600, 2)

        if approval_time and created_at:
            time_to_first_approval = round((approval_time - created_at).total_seconds() / 3600, 2)

        if approval_time and merged_at:
            time_from_approval_to_merge = round((merged_at - approval_time).total_seconds() / 3600, 2)

        return [
            pr_number,
            created_at.strftime("%Y-%m-%d %H:%M:%S") if created_at else None,
            merged_at.strftime("%Y-%m-%d %H:%M:%S") if merged_at else None,
            time_to_merge,
            first_review_start,
            time_to_first_review,
            time_to_first_approval,
            time_from_approval_to_merge,
        ]
    except Exception as e:
        print(f"Error processing PR #{pr_number}: {e}")
        return None


def write_to_csv(data, filename="pr_review_metrics.csv"):
    """Write the processed data to a CSV file."""
    headers = [
        "PR Number",
        "Created At",
        "Merged At",
        "Time to Merge (hours)",
        "First Review Time",
        "Time to First Review (hours)",
        "Time to First Approval (hours)",
        "Time from Approval to Merge (hours)",
    ]

    with open(filename, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(headers)
        writer.writerows(data)


def main():
    """Main function to run the PR metrics collection."""
    parser = argparse.ArgumentParser(description="Generate PR review metrics.")
    parser.add_argument(
        "-o", "--output", default="pr_review_metrics.csv", help="Output CSV filename (default: pr_review_metrics.csv)"
    )
    parser.add_argument("-l", "--limit", type=int, help="Limit the number of PRs to process")
    parser.add_argument(
        "-r", "--repo", required=True, help="GitHub repository in format 'owner/repo' (e.g., 'octocat/Hello-World')"
    )
    args = parser.parse_args()

    if not TOKEN:
        print("Error: GitHub token must be set in environment variables.")
        print("Please set GITHUB_TOKEN_READONLY_WEB or GITHUB_TOKEN")
        return

    try:
        repo = validate_repo_format(args.repo)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    print(f"Fetching PR data for repository: {repo}")

    prs = fetch_pull_requests(repo)

    if args.limit and args.limit > 0:
        prs = prs[: args.limit]
        print(f"Processing limited set of {len(prs)} pull requests...")
    else:
        print(f"Processing {len(prs)} pull requests...")

    results = []
    for i, pr in enumerate(prs):
        result = process_pr(repo, pr)
        if result:
            results.append(result)
        if (i + 1) % 10 == 0 or i == len(prs) - 1:
            print(f"Processed {i + 1}/{len(prs)} PRs")

    write_to_csv(results, args.output)
    print(f"Saved metrics for {len(results)} PRs to {args.output}")

    # Print quick summary
    merged_prs = [r for r in results if r[2] is not None]
    if merged_prs:
        merge_times = [r[3] for r in merged_prs if r[3] is not None]
        review_times = [r[5] for r in merged_prs if r[5] is not None]

        if merge_times:
            avg_merge_time = sum(merge_times) / len(merge_times)
            print(f"Average time to merge: {avg_merge_time:.2f} hours")

        if review_times:
            avg_review_time = sum(review_times) / len(review_times)
            print(f"Average time to first review: {avg_review_time:.2f} hours")


if __name__ == "__main__":
    main()
