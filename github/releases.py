import os
import requests
from collections import defaultdict

# Retrieve the access token from the environment variable
access_token = os.environ.get('GITHUB_TOKEN_READONLY_WEB')

# Set the repository owner and name
owner = 'onfleet'
repo = 'web'

# Set the API endpoint URL
url = f'https://api.github.com/repos/{owner}/{repo}/tags'

# Set the request headers
headers = {
    'Authorization': f'token {access_token}',
    'Accept': 'application/vnd.github.v3+json'
}

# Set the query parameters
params = {
    'per_page': 100,  # Number of items per page
    'since': '2022-12-31T23:59:59Z'  # Filter releases after 2023-12
}

# Create a dictionary to store releases by year and month
releases_by_month = defaultdict(list)

# Retrieve releases from all pages
while url:
    # Send a GET request to retrieve the tags
    response = requests.get(url, headers=headers, params=params)

    # Check if the request was successful
    if response.status_code == 200:
        # Parse the JSON response
        tags = response.json()

        # Sort the releases into the dictionary
        for tag in tags:
            if tag['name'].startswith('release-'):
                release_date = tag['name'].split('release-')[1]
                year_month = release_date[:7]
                releases_by_month[year_month].append(tag['name'])

        # Check if there are more pages
        if 'next' in response.links:
            url = response.links['next']['url']
        else:
            url = None
    else:
        print(f'Error: {response.status_code} - {response.text}')
        break

# Print the releases enumerated by year and month with the month sum
for year_month, releases in sorted(releases_by_month.items()):
    year, month = year_month.split('-')
    month_sum = len(releases)
    print(f"{year}-{month}: {month_sum}")
    for index, release in enumerate(releases, start=1):
        print(f"  {index}. {release}")
    print()


# # Send a GET request to retrieve the tags
# response = requests.get(url, headers=headers)

# # Check if the request was successful
# if response.status_code == 200:
#     # Parse the JSON response
#     tags = response.json()

#     # Create a dictionary to store releases by year and month
#     releases_by_month = defaultdict(list)

#     # Sort the releases into the dictionary
#     for tag in tags:
#         if tag['name'].startswith('release-'):
#             release_date = tag['name'].split('release-')[1]
#             year_month = release_date[:7]
#             releases_by_month[year_month].append(tag['name'])

#     # Print the releases enumerated by year and month
#     for year_month, releases in sorted(releases_by_month.items()):
#         year, month = year_month.split('-')
#         month_sum = len(releases)
#         print(f"{year}-{month}: {month_sum}")
#         for index, release in enumerate(releases, start=1):
#             print(f"  {index}. {release}")
#         print()
# else:
#     print(f'Error: {response.status_code} - {response.text}')
