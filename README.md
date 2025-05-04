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

## Repository Structure

```
├── git_metrics/                        # Scripts for analyzing GitHub repository metrics
│   ├── README.md                      # Documentation for git metrics scripts
│   ├── developer_activity_insight.py   # Comprehensive PR metrics and developer activity analysis
│   ├── releases.py                     # Analyze release patterns
│   ├── lines_changed.py                # Track code volume changes
│   ├── repo_commit_report.sh           # Generate commit reports for multiple repos
│   ├── code_review_metrics.py          # Analyze code review patterns and timing
│   ├── ci_pr_performance_metrics.py    # Analyze PR and CI metrics
│   ├── active_devs_one_off.py          # Track active developers
│   ├── active_repos_one_off.py         # Identify active repositories
│
├── jira_metrics/                       # Scripts for extracting metrics from Jira
│   ├── engineering_excellence.py       # Track engineering excellence vs product work
│   ├── cycle_time.py                   # Analyze time from code review to release
│   ├── release_failure.py              # Analyze release failures and impact
│   ├── individual.py                   # Individual contributor metrics analysis
│   ├── released_tickets.py             # Track monthly released ticket counts
│   ├── jira_utils.py                   # Helper utility 
│
├── tests/                              # Test suite
│   ├── __init__.py       
│   ├── test_engineering_excellence.py
│ 
├── .gitignore                          # Git ignore file
├── requirements.txt                    # Python dependencies
└── README.md                           # This file
```

## Requirements

Install the necessary python frameworks with: 
```bash
python3 -m venv venv
source venv/bin/activate
pip3 install --upgrade -r requirements.txt
```

If you make python dependency changes, please update requirements.txt with:
```bash
pip3 freeze > requirements.txt
```

## Key Components

### Git Metrics
Scripts for analyzing GitHub repository metrics and developer activity:
- `developer_activity_insight.py`: Comprehensive PR metrics including monthly aggregations, review metrics, and volume metrics per author
- `releases.py`: Analyze release patterns and frequencies
- `lines_changed.py`: Track code volume changes between dates
- `repo_commit_report.sh`: Generate detailed commit reports for multiple repositories
- `code_review_metrics.py`: Analyze code review patterns and timing
- `ci_pr_performance_metrics.py`: Track CI performance metrics for PRs
- `active_devs_one_off.py`: Identify and analyze active developers
- `active_repos_one_off.py`: Identify and analyze active repositories

### Jira Metrics
Scripts for extracting and analyzing Jira metrics:
- `engineering_excellence.py`: Track engineering excellence vs product work
- `cycle_time.py`: Calculate cycle time metrics
- `release_failure.py`: Analyze release failures and impact
- `individual.py`: Individual contributor metrics analysis
- `released_tickets.py`: Track monthly released ticket counts
- `jira_utils.py`: Helper utility module

## Environment Variables

Create an `.env` file in the root directory with the following variables:

```
# GitHub Configuration
GITHUB_TOKEN_READONLY_WEB="your_github_token"
GITHUB_METRIC_OWNER_OR_ORGANIZATION="your_github_org"
GITHUB_REPO_FOR_RELEASE_TRACKING="your_repo_name"
GITHUB_REPO_FOR_PR_TRACKING="your_repo_name"

# Jira Configuration
USER_EMAIL="your_email@example.com"
JIRA_API_KEY="your_jira_api_key"
JIRA_LINK="https://your_jira_instance.atlassian.net"
JIRA_GRAPHQL_URL="https://your_jira_instance.atlassian.net/gateway/api/graphql"
JIRA_PROJECTS="PROJECT1,PROJECT2,PROJECT3"

# Team Configuration
TEAM_<NAME>="team_name"  # Used when team field isn't available in project

# Jira Custom Fields (example values - replace with your actual field IDs)
CUSTOM_FIELD_STORYPOINTS=10025
CUSTOM_FIELD_TEAM=10075
CUSTOM_FIELD_WORK_TYPE=10079
```

Note: The custom field IDs are examples. You'll need to find your actual field IDs in Jira under Settings → Issues → Custom Fields.

## Example Usage

### GitHub Metrics
To analyze developer activity and PR metrics:
```bash
python3 git_metrics/developer_activity_insight.py --repos 'org/repo1,org2/repo2' --users 'user1,user2' --date_start '2024-01-01' --date_end '2024-03-31'
```

To analyze release patterns:
```bash
python3 git_metrics/releases.py
```

### Jira Metrics
To analyze engineering excellence:
```bash
python3 jira_metrics/engineering_excellence.py
```

To analyze cycle times:
```bash
python3 jira_metrics/cycle_time.py
```
