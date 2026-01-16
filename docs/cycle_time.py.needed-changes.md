## Low Findings (Testability Improvements)

### Add unit tests for new month and per-assignee paths

- **Problem**: `parse_month()` and `--individuals-month` behavior are logic-only changes with no unit tests.
- **Impact**: Parsing or aggregation regressions may go unnoticed until runtime.
- **Where**: `jira_metrics/cycle_time.py` (`parse_month`, `calculate_monthly_cycle_time`, `process_cycle_time_metrics`)
- **Recommended change**:
  - Add unit tests for `parse_month()` bounds (1-12) and error handling.
  - Add a small unit test to verify per-assignee aggregation and printing for a selected month.
