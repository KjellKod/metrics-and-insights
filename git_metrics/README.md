# Git Metrics Scripts

This directory contains scripts for analyzing GitHub repository metrics.

## Scripts

### developer_activity_insight.py
Generates comprehensive PR metrics reports including monthly aggregations, review metrics, and volume metrics per author.

Metrics collected:
- PR Details: date, author, repository, PR number, lines changed, time to merge
- Monthly Aggregations: PR counts, median hours to merge, lines added/removed, total changes
- Author-specific Metrics: PR count per author, median hours to merge, lines added/removed
- Review Metrics: reviews participated, reviews approved, comments made

Required Environment Variables:
- `GITHUB_TOKEN_READONLY_WEB`: GitHub Personal Access Token with repo read access

```bash
python3 developer_activity_insight.py [options]
Options:
  --repos REPOS         Comma-separated list of GitHub repos (e.g., 'org1/repo1,org2/repo2')
  --users USERS         Comma-separated list of GitHub usernames
  --date_start DATE     Start date in YYYY-MM-DD format
  --date_end DATE       End date in YYYY-MM-DD format
  --output FILE         Output CSV file name (default: pr_metrics.csv)
  --debug               Enable debug logging
```

### releases.py
Tracks and analyzes GitHub releases, providing monthly release counts and detailed release information.

```bash
python3 releases.py
```

### lines_changed.py
Analyzes code changes by tracking additions and deletions across commits within a specified date range.

```bash
python3 lines_changed.py --start-date <YYYY-MM-DD> --end-date <YYYY-MM-DD>
```

### repo_commit_report.sh
Generates a detailed commit report for multiple repositories within a specified date range, useful for audits and oversight activities.

```bash
./repo_commit_report.sh --start-date <YYYY-MM-DD> --end-date <YYYY-MM-DD> --repos <owner1/repo1,owner2/repo2>
```

### code_review_metrics.py [graphQL proof-of-concept]
Generates metrics about PR review times and approvals.

```bash
python code_review_metrics.py -r owner/repo [options]
```

Options:
- `-r, --repo`     GitHub repository in format 'owner/repo' (required)
- `-o, --output`   Output CSV filename (default: pr_review_metrics.csv)
- `-l, --limit`    Limit the number of PRs to process

Note: This script is deprecated. Please use `developer_activity_insight.py` instead, which provides the same functionality plus additional metrics.

### ci_pr_performance_metrics.py
Tracks CI performance metrics for PRs, including build times, success rates, and their relationship to PR merge times.

```bash
python3 ci_pr_performance_metrics.py [options]
Options:
  -v, --verbose           Enable verbose output for debugging
  --force-fresh          Ignore existing cache and fetch fresh data from GitHub
  --load-from-file FILE  Load data from a specified cache file
  --save-to-file FILE    Save retrieved data to a specified file
  --start-date DATE      Start date for PR analysis (format: YYYY-MM-DD, default: 2024-01-01)
```

### active_devs_one_off.py
One-time script to identify and analyze active developers in the repository.

```bash
python3 active_devs_one_off.py
```

### active_repos_one_off.py
One-time script to identify and analyze active repositories in the organization.

```bash
python3 active_repos_one_off.py
```