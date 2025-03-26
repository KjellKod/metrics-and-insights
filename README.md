# Engineering Metrics and Insights

This repository contains a collection of scripts for gathering and analyzing engineering metrics from Jira and GitHub. The goal is to help engineering teams identify areas for process improvement, track progress, and make data-driven decisions.

## Purpose and Usage

These tools are designed to provide insights into various aspects of the software development lifecycle:

- **Delivery Performance**: Track cycle times, release frequencies, and release failures
- **Engineering Excellence**: Monitor balance between product work and technical improvements
- **Code Review Process**: Analyze PR review times and patterns
- **Team Workload**: Understand ticket distribution and completion patterns

### Important Note on Metrics
These metrics should be used as conversation starters and indicators, not as absolute measures of performance. They are most valuable when:
- Used to identify trends over time
- Combined with qualitative feedback
- Discussed openly with teams
- Used to find areas needing support or improvement

### Data Export and Visualization
Most scripts include a `-csv` flag that exports data to CSV files, making it easy to:
- Import into spreadsheet tools (Google Sheets, Excel)
- Create custom dashboards
- Combine with other data sources
- Share insights with stakeholders
- Track trends over time

Example workflow:
1. Run scripts regularly (e.g., monthly)
2. Export to CSV
3. Import into shared spreadsheet
4. Create visualizations
5. Discuss trends with team


## Repository Structure ##

```
├── git_metrics/                        # Scripts for analyzing GitHub repository metrics
│   ├── releases.py                     # Analyze release patterns
│   ├── lines_changed.py                # Track code volume changes
|   |── repo_commit_report.sh
│   ├── ci_pr_performance_metrics.py    # Analyze PR and CI metrics
|   ├── active_devs_one_off.py          # Track active developers
|   ├── active_repos_one_off.py         # Identify active repositories
│
│
├── jira_metrics/                   # Scripts for extracting metrics from Jira
│   ├── engineering_excellence.py   # Track engineering excellence vs product wor
│   ├── cycle_time.py               # Analyze time from code review to release
│   ├── release_failure.py          # Analyze release failures and impact
│   ├── individual.py               # Individual contributor metrics analysis
│   ├── released_tickets.p          # Track monthly released ticket counts
│   ├── jira_utils.py               # helper utility 
│
├── tests/                # Test suite
│   ├── __init__.py       
│   ├── test_engineering_excellence.py
| 
├── .gitignore            # to ignore
├── requirements.txt      # dependencies
└── README.md             # overview
```


## Important Note on Metrics
These metrics should be used as conversation starters and indicators, not as absolute measures of performance. They are most valuable when:
- Used to identify trends over time
- Combined with qualitative feedback
- Discussed openly with teams
- Used to find areas needing support or improvement


## Jira Metrics -- Key Components  ##

*jira_metrics/*
Scripts for extracting various engineering metrics from Jira:

- **cycle_time.py**: Calculates and analyzes cycle time from code review to release status. Shows median and average cycle times per team and outputs monthly trends. Helps identify delivery pipeline bottlenecks.

- **engineering_excellence.py**: Tracks the balance between product work and engineering excellence initiatives (debt reduction, critical work). Provides monthly breakdowns per team and calculates running annual averages for engineering excellence focus.

- **individual.py**: Analyzes individual contributor metrics including points completed and ticket counts. Supports team or project-based analysis and shows top contributors over rolling periods. Note: intended for identifying support needs, not performance evaluation.

- **jira_utils.py**: Shared utility module providing common functionality like:
  - Jira authentication and connection handling
  - Status tracking and timestamp analysis
  - Team and project configuration
  - CSV export capabilities
  - Argument parsing and verbose logging

- **release_failure.py**: Analyzes release tickets and their linked work items to track:
  - Release success/failure rates
  - Impact of failed releases (affected tickets)
  - Monthly and annual failure trends per team

- **released_tickets.py**: Provides monthly statistics on successfully released tickets including:
  - Ticket counts per team/project
  - Story point tracking (when available)
  - Month-over-month release velocity

## Git Metrics -- Key Components  ##

*git_metrics/*
Scripts for extracting metrics from GitHub repositories:

- **active_devs_one_off.py**: One-off script to identify active developers within a specified timeframe (default 60 days). Shows:
  - Developer activity patterns
  - Contribution frequency
  - Active developer count

- **active_repos_one_off.py**: One-off script to identify active repositories in your organization:
  - Lists repositories with recent PR activity
  - Shows PR counts and last activity dates
  - Helps identify maintenance needs

- **ci_pr_performance_metrics.py**: Comprehensive analysis of PR and CI performance:
  - Merge time statistics
  - CI build durations
  - Review patterns
  - Success/failure rates
  - Monthly and yearly trends
  Options:
  ```bash
  -v, --verbose           Enable verbose output
  --force-fresh          Ignore cache and fetch fresh data
  --load-from-file FILE  Load from cached data file
  --save-to-file FILE    Save data to cache file
  --start-date DATE      Analysis start date (YYYY-MM-DD)
  ```
- **lines_changed.py**: Analyzes code volume changes over time:
  - Tracks additions and deletions
  - Shows net code changes
  - Supports date range analysis
  Usage:
  ```bash
  python3 git_metrics/lines_changed.py --start-date YYYY-MM-DD --end-date YYYY-MM-DD
  ```
- **releases.py**: Tracks and analyzes release patterns:
  - Monthly release counts
  - Release naming patterns
  - Release frequency trends
  - Supports CSV export with -csv flag

### Data Export
Most scripts support data export for further analysis:


### Data Export
Many scripts support CSV export via the `-csv` flag for further analysis or dashboard creation. Example usage:


## Requirements ##

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

# TEAM_<ONE> etc is used for when the team field isn't used in for a project but might make sense see 
# example export TEAM_SWE="scandinavian_group"
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
