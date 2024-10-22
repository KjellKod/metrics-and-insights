# pylint: disable=missing-timeout
import os
from collections import defaultdict
import argparse
import csv
import requests


# Retrieve the access token from the environment variable
access_token = os.environ.get("GITHUB_TOKEN_READONLY_WEB")

# Set the repository owner and name
owner = os.environ.get("GITHUB_METRIC_OWNER")
repo = os.environ.get("GITHUB_METRIC_REPO")

# Set the API endpoint URL
URL = f"https://api.github.com/repos/{owner}/{repo}/tags"

# Set the request headers
headers = {
    "Authorization": f"token {access_token}",
    "Accept": "application/vnd.github.v3+json",
}

# Set the query parameters
params = {
    "per_page": 100,  # Number of items per page
    "since": "2023-12-31T23:59:59Z",  # Filter releases after 2023-12
    "timeout": 10,  # Timeout in seconds
}

# Create a dictionary to store releases by year and month
releases_by_month = defaultdict(list)

# Retrieve releases from all pages
while URL:
    # Send a GET request to retrieve the tags
    response = requests.get(URL, headers=headers, params=params)

    # Check if the request was successful
    if response.status_code == 200:
        # Parse the JSON response
        tags = response.json()

        # Sort the releases into the dictionary
        for tag in tags:
            if tag["name"].startswith("release-"):
                release_date = tag["name"].split("release-")[1]
                year_month = release_date[:7]
                releases_by_month[year_month].append(tag["name"])

        # Check if there are more pages
        if "next" in response.links:
            URL = response.links["next"]["url"]
        else:
            URL = None
    else:
        print(f"Error: {response.status_code} - {response.text}")
        break

# Print the releases enumerated by year and month with the month sum
for year_month, releases in sorted(releases_by_month.items()):
    year, month = year_month.split("-")
    month_sum = len(releases)
    print(f"{year}-{month}: {month_sum}")
    for index, release in enumerate(releases, start=1):
        print(f"  {index}. {release}")
    print()


# Parse command-line arguments
parser = argparse.ArgumentParser(
    description="Retrieve and optionally export GitHub releases to CSV."
)
parser.add_argument(
    "-csv", action="store_true", help="Export the release data to a CSV file."
)
args = parser.parse_args()

# Export to CSV if the -csv flag is provided
if args.csv:
    with open("releases.csv", "w", newline="", encoding="utf-8") as csvfile:
        fieldnames = ["Month", "Release Count", "Named Releases"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        writer.writeheader()
        for year_month, releases in sorted(releases_by_month.items()):
            release_count = len(releases)
            NAMED_RELEASES = "\n".join(releases)
            writer.writerow(
                {
                    "Month": year_month,
                    "Release Count": release_count,
                    "Named Releases": NAMED_RELEASES,
                }
            )
    print("Release data has been exported to releases.csv")
else:
    print("To save output to a CSV file, use the -csv flag.")
