```
from GitHub
│   ├── releases.py
│   ├── pr_metrics.py
│   ├── lines_changed.py
|   |── repo_commit_report.sh
│
│
├── jira/                 # Scripts for extracting metrics from Jira
│   ├── engineering_excellence.py
│   ├── cycle_time.py
│   ├── release_failure.py
│   ├── released_tickets.py
│   ├── jira_utils.py # helper utility 
│
├── tests/                # Test suite
│   ├── __init__.py       
│   ├── test_engineering_excellence.py
| 
├── .gitignore            # to ignore
├── requirements.txt      # dependencies
└── README.md             # overview
```

## Requirementsi ##
Install the necessary python frameworks with: 
```
python3 -m venv venv
source venv/bin/activate
pip3 install --upgrade -r requirements.txt
```

If you do python dependency changes, please add them later in your virtual environment with 
`pip3 freeze requirements.txt`

## Key Components ##
*github/*
Scripts for extracting metrics from GitHub based on the release tags 
- releases.py: Script to retrieve and categorize GitHub releases by year and month.
- pr_metrics.py: Script to analyze Pull Request (PR) metrics, including merge times and GitHub Actions check durations.
- lines_changed.py: Script to see line changes between two dates. This is just a for-fun insight that can show how much / little changes over time in repositories. It does not take into account the importance of the changes. `GITHUB_METRIC_OWNER_OR_ORGANIZATION=<organization>` and `GITHUB_METRIC_REPO=<repo-name>` needs to be defined in environment variables. 
- repo_commit_report.sh: Bash script to generate repository commit information for a time range for one or multiple repositories

*jira/* 
Scripts for extracting metrics from Jira.

- engineering_excellence.py: Script to extract engineering excellence metrics from Jira. It shows for each team and month the product focus, engineering excellence focus (debt reductino, critical work) and the annual average SO FAR of ee
- cycle_time.py: Script to calculate cycle time metrics from Jira, based on when coding is finished until it's marked as released. 
- release_failure.py: Script extract all `Release` tickets, the linked tickets part of that release and whether or not the release was a failure. 
- released_tickets.py: Retrieve calculate amount of released tickets month-by-month.
- jira_utils.py: Helper utility module containing common functions and utilities used across other Jira scripts

## PR Metrics Analysis
To analyze PR metrics, use the following command:

```bash
python3 github/pr_metrics.py [options]

Options:

-v, --verbose: Enable verbose output
-csv: Export the release data to a CSV file
-load-from-file FILENAME: Load data from a specified file instead of querying GitHub
-save-to-file FILENAME: Save retrieved data to a specified file
This script calculates and displays metrics for merged Pull Requests, including:

Total number of PRs per month
Median merge time (in hours) per month
Median and average check time (in minutes) per month
Ratio of check time to merge time (as a percentage)
The script retrieves data for PRs that have been merged since January 1, 2024, by default.
```

- Setup and Usage

## Environmental Variables## 
Some scripts require environmental variables to be set. Create an .env file in the root of the directory and set these values. 
As an alternative, you can set these in your .zshrc or .bashrc file:

### .env format
```
USER_EMAIL="your_email@example.com"
JIRA_API_KEY="your_jira_api_key"
```

### All variables needed and described in .env format (root of repo)
```
USER_EMAIL="your_email@example.com"
JIRA_API_KEY="your_jira_api_key"
JIRA_LINK="https://your_jira_instance.atlassian.net"
JIRA_GRAPHQL_URL = "https://<your_jira_instance>.atlassian.net/gateway/api/graphql"
GITHUB_TOKEN_READONLY_WEB="your_github_token"
GITHUB_METRIC_OWNER_OR_ORGANIZATION="your_github_repo_owner_or_organization"
GITHUB_REPO_FOR_RELEASE_TRACKING="your_github_repo_name"
JIRA_PROJECTS="MYPROJECT, ENG, ETC"
TEAM_<NAME>="a team name, for issues when they can't be parsed or doesn't exist in team-only project the <NAME> should correspond to the PROJECT" 

# NOTE the customfield enumerations here are examples, your jira project WILL BE DIFFERENT
# Settings --> Issues --> CustomFields: search for your definition of these variables
CUSTOM_FIELD_STORYPOINTS=10025
CUSTOM_FIELD_TEAM=10075
CUSTOM_FIELD_WORK_TYPE=10079
CUSTOM_FIELD_STORYPOINTS=10025
```

### All variables needed and described in zshrc format
```
export USER_EMAIL="your_email@example.com"
export JIRA_API_KEY="your_jira_api_key"
export JIRA_LINK="https://your_jira_instance.atlassian.net"
export JIRA_GRAPHQL_URL = "https://<your_jira_instance>.atlassian.net/gateway/api/graphql"
export GITHUB_TOKEN_READONLY_WEB="your_github_token"
export GITHUB_METRIC_OWNER_OR_ORGANIZATION="your_github_repo_owner"
export GITHUB_METRIC_REPO="your_github_repo_name"
export JIRA_PROJECTS="MYPROJECT, ENG, ETC"
export RELEASE_INSIGHT_PROJECT="MY_PROJECT_TRACKING_RELEASES"
export TEAM_ONE="first_team" 

# NOTE the customfield enumerations here are examples, your jira project WILL BE DIFFERENT
# Settings --> Issues --> CustomFields: search for your definition of these variables
export CUSTOM_FIELD_STORYPOINTS=10025
export CUSTOM_FIELD_TEAM=10075
export CUSTOM_FIELD_WORK_TYPE=10079
export CUSTOM_FIELD_STORYPOINTS=10025

# -- used for when the `team` field isn't defined for a project
# example export TEAM_INT="mint"
```


## Example Usage ##
Extracting GitHub Releases
To retrieve and categorize GitHub releases, ensure your environmental variables are set and run:

`python3 github/releases.py`


## Team and Individual Metrics. 
A word of caution. These metrics are by itself not very valuable, they can however more easily help you see where a team and an individual are struggling or needs support.
The metrics should be seen as a clue as to where it's needed to dig in more, to ask questions and understand the situation that is driving the metric up/down. 


## Tests ## 
`pytest -v` 

alternatively: 
In each functionality directory, if it has a test directory you can run all of the tests like this 

`python3 -m unittest discover -s tests -p "*.py"`

Or more verbose with `-v` flag. You can also specify the individual file. 

`python3 -m unittest discover -v -s tests -p test_engineering_excellence.py`

## Branches
[Trick to update your branch to latest on main, in the github UI](https://github.com/USERNAME/REPOSITORY_NAME/compare/feature-branch...main)
