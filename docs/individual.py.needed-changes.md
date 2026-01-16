## High Findings

### Configured completion statuses are not honored in aggregation logic

- **Problem**: `construct_jql()` uses `get_completion_statuses()` to filter tickets, but
  `calculate_individual_jira_metrics()` still only recognizes `Released`/`Done` when
  aggregating results, which can drop tickets in other configured completion statuses.
- **Impact**: Missing tickets and inaccurate per-assignee totals when completion statuses
  differ from the hard-coded set.
- **Where**: `jira_metrics/individual.py` (`construct_jql` and `calculate_individual_jira_metrics`)
- **Recommended change**:
  - Use `get_completion_statuses()` in aggregation logic to find the most recent completion timestamp.
  - Avoid mutating status casing in JQL (the current code calls `.title()`), use configured values verbatim.


## Low Findings (Testability Improvements)

### Add unit tests for new logic

- **Target areas**:
  - `construct_jql()` uses configured completion statuses (no casing mutation).
  - Aggregation respects configured completion statuses (not only `Released/Done`).
  - `print_year_summary()` totals are correct for multi-month, multi-team inputs.
  - `parse_month()` bounds handling (1–12) in `jira_metrics/cycle_time.py`.
  - Per-assignee cycle time stats for `--individuals-month`.
- **Suggested location**:
  - `jira_metrics/tests/test_individual.py` (new or existing) for `individual.py` logic.
  - `jira_metrics/tests/test_cycle_time.py` for `cycle_time.py` helpers.
