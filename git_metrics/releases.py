# pylint: disable=missing-timeout
import os
from collections import defaultdict
import argparse
import csv
import requests
from dotenv import load_dotenv


def load_config():
    """Load environment variables and return config dict"""
    load_dotenv()
    return {
        "access_token": os.environ.get("GITHUB_TOKEN_READONLY_WEB"),
        "owner": os.environ.get("GITHUB_METRIC_OWNER_OR_ORGANIZATION"),
        "repo": os.environ.get("GITHUB_REPO_FOR_RELEASE_TRACKING"),
    }


def get_api_headers(access_token):
    """Return API headers for GitHub requests"""
    return {
        "Authorization": f"token {access_token}",
        "Accept": "application/vnd.github.v3+json",
    }


def fetch_releases(config):
    """Fetch all releases from GitHub API"""
    releases_by_month = defaultdict(list)
    url = f"https://api.github.com/repos/{config['owner']}/{config['repo']}/tags"
    headers = get_api_headers(config["access_token"])
    params = {
        "per_page": 100,
        "since": "2023-12-31T23:59:59Z",
        "timeout": 10,
    }

    while url:
        response = requests.get(url, headers=headers, params=params)

        if response.status_code == 200:
            tags = response.json()

            for tag in tags:
                if tag["name"].startswith("release-"):
                    release_date = tag["name"].split("release-")[1]
                    year_month = release_date[:7]
                    releases_by_month[year_month].append(tag["name"])

            url = response.links.get("next", {}).get("url")
        else:
            print(f"Error: {response.status_code} - {response.text}")
            break

    return releases_by_month


def c_print_releases(releases_by_month):
    """Print releases grouped by month"""
    for year_month, releases in sorted(releases_by_month.items()):
        year, month = year_month.split("-")
        month_sum = len(releases)
        print(f"{year}-{month}: {month_sum}")
        for index, release in enumerate(releases, start=1):
            print(f"  {index}. {release}")
        print()


def b_export_to_csv(releases_by_month):
    """Export releases data to CSV file"""
    with open("releases.csv", "w", newline="", encoding="utf-8") as csvfile:
        fieldnames = ["Month", "Release Count", "Named Releases"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        writer.writeheader()
        for year_month, releases in sorted(releases_by_month.items()):
            writer.writerow(
                {
                    "Month": year_month,
                    "Release Count": len(releases),
                    "Named Releases": "\n".join(releases),
                }
            )
    print("Release data has been exported to releases.csv")


def a_parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description="Retrieve and optionally export GitHub releases to CSV.")
    parser.add_argument("-csv", action="store_true", help="Export the release data to a CSV file.")
    return parser.parse_args()


def main():
    """Main function to orchestrate the release data retrieval and display"""
    config = load_config()
    releases_by_month = fetch_releases(config)
    print_releases(releases_by_month)

    args = parse_arguments()
    if args.csv:
        export_to_csv(releases_by_month)
    else:
        print("To save output to a CSV file, use the -csv flag.")


if __name__ == "__main__":
    main()
