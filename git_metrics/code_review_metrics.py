# pylint: disable=missing-timeout
import requests
import csv
import os
import argparse
from datetime import datetime
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

# ========== CONFIGURATION ========== #
GITHUB_API_URL = "https://api.github.com"
OWNER = os.environ.get("GITHUB_METRIC_OWNER_OR_ORGANIZATION")
REPO_NAME = os.environ.get("GITHUB_REPO_FOR_PR_TRACKING")
REPO = f"{OWNER}/{REPO_NAME}" if OWNER and REPO_NAME else os.environ.get("REPO")
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


# ========== FETCH PULL REQUESTS ========== #
def fetch_pull_requests(state="closed", per_page=100):
    """Fetch all pull requests with pagination."""
    all_prs = []
    page = 1

    while True:
        url = f"{GITHUB_API_URL}/repos/{REPO}/pulls"
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
            else:
                break
        except requests.RequestException as e:
            print(f"Error fetching PRs: {e}")
            break

    print(f"Total PRs fetched: {len(all_prs)}")
    return all_prs


# ========== FETCH PR REVIEWS ========== #
def fetch_reviews(pr_number):
    """Fetch all reviews for a pull request."""
    url = f"{GITHUB_API_URL}/repos/{REPO}/pulls/{pr_number}/reviews"
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
            else:
                break
        except requests.RequestException as e:
            print(f"Error fetching reviews for PR #{pr_number}: {e}")
            break

    return all_reviews


# ========== FETCH PR TIMELINE EVENTS ========== #
def fetch_timeline(pr_number):
    """Fetch timeline events for a pull request."""
    url = f"{GITHUB_API_URL}/repos/{REPO}/issues/{pr_number}/timeline"
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
            else:
                break
        except requests.RequestException as e:
            print(f"Error fetching timeline for PR #{pr_number}: {e}")
            break

    return all_events


# ========== PROCESS PR DATA ========== #
def process_pr(pr):
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
        reviews = fetch_reviews(pr_number)

        # Get timeline events for review requests
        timeline = fetch_timeline(pr_number)

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
        print(f"Error processing PR #{pr.get('number', 'Unknown')}: {str(e)}")
        return [
            pr.get("number", "Unknown"),
            pr.get("created_at", "Unknown"),
            None,
            None,
            None,
            None,
            None,
            None,
        ]


# ========== WRITE CSV ========== #
def write_to_csv(data, filename="pr_review_metrics.csv"):
    """Write PR metrics to a CSV file."""
    headers = [
        "PR Number",
        "Created At",
        "Merged At",
        "Time to Merge (h)",
        "First Review Start",
        "Time to First Review (h)",
        "Time to First Approval (h)",
        "Time from Approval to Merge (h)",
    ]

    # Make a copy of the data to format dates for CSV display
    formatted_data = []
    for row in data:
        formatted_row = row.copy() if isinstance(row, list) else row[:]

        # Format dates in positions 1, 2, and 4 (Created At, Merged At, First Review Start)
        for i in [1, 2, 4]:
            if i < len(formatted_row) and formatted_row[i]:
                # If it's already a date string, try to simplify it
                if isinstance(formatted_row[i], str) and "T" in formatted_row[i]:
                    try:
                        dt = datetime.strptime(formatted_row[i], "%Y-%m-%dT%H:%M:%SZ")
                        formatted_row[i] = dt.strftime("%Y-%m-%d")
                    except ValueError:
                        pass
                # If it's a date with time, simplify to just date
                elif isinstance(formatted_row[i], str) and " " in formatted_row[i]:
                    try:
                        dt = datetime.strptime(formatted_row[i], "%Y-%m-%d %H:%M:%S")
                        formatted_row[i] = dt.strftime("%Y-%m-%d")
                    except ValueError:
                        pass

        formatted_data.append(formatted_row)

    try:
        with open(filename, mode="w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(headers)
            writer.writerows(formatted_data)
    except IOError as e:
        print(f"Error writing to CSV file: {e}")


# ========== MAIN PIPELINE ========== #
def main():
    """Main function to run the PR metrics collection."""
    parser = argparse.ArgumentParser(description="Generate PR review metrics.")
    parser.add_argument(
        "-o", "--output", default="pr_review_metrics.csv", help="Output CSV filename (default: pr_review_metrics.csv)"
    )
    parser.add_argument("-l", "--limit", type=int, help="Limit the number of PRs to process")
    args = parser.parse_args()

    if not REPO or not TOKEN:
        print("Error: Repository and GitHub token must be set in environment variables.")
        print("Please set GITHUB_METRIC_OWNER_OR_ORGANIZATION and GITHUB_REPO_FOR_PR_TRACKING")
        print("or alternatively set REPO as 'owner/repo'")
        print("And set GITHUB_TOKEN_READONLY_WEB or GITHUB_TOKEN for authentication.")
        return

    print(f"Fetching PR data for repository: {REPO}")

    prs = fetch_pull_requests()

    if args.limit and args.limit > 0:
        prs = prs[: args.limit]
        print(f"Processing limited set of {len(prs)} pull requests...")
    else:
        print(f"Processing {len(prs)} pull requests...")

    results = []
    for i, pr in enumerate(prs):
        result = process_pr(pr)
        results.append(result)
        if (i + 1) % 10 == 0 or i == len(prs) - 1:
            print(f"Processed {i + 1}/{len(prs)} PRs")

    write_to_csv(results, args.output)
    print(f"Saved metrics for {len(results)} PRs to {args.output}")

    # Print quick summary
    merged_prs = [r for r in results if r[2] is not None]  # Has merge time
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
