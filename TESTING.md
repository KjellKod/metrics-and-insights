## Testing Approach (Current)

- Tests are organized by module in `jira_metrics/tests/` and `git_metrics/tests/`.
- The suite uses Python's `unittest` with explicit path manipulation for local imports.
- Pure logic is often tested directly (e.g., time calculations in `cycle_time.py`).
- External dependencies (Jira/GitHub APIs, environment, filesystem) are mocked or isolated.

## Where to Add Tests

- **Jira metrics**: add tests under `jira_metrics/tests/` with `test_<module>.py`.
- **Git metrics**: add tests under `git_metrics/tests/` with `test_<module>.py`.
- Follow the existing test setup pattern with path manipulation for local imports.

## How to Run Tests

From the project root:

- Run all tests:
  - `python3 -m pytest`
- Run a specific file:
  - `python3 -m pytest jira_metrics/tests/test_bug_stats.py`
- Run with coverage:
  - `python3 -m pytest --cov=jira_metrics`
- CI-equivalent local checks:
  - `./pr_readiness.sh`

## Strengths

- Clear coverage of core logic and edge cases in time calculations.
- External API calls are mocked to avoid network reliance.
- Tests isolate filesystem side effects (e.g., temp dirs in cache tests).

## Opportunities (Brief)

- Add tests alongside new CLI flags and reporting paths when logic is added.
- Prefer small unit tests for helpers (`parse_month`, per-assignee aggregation) to prevent regressions.
- Keep mocks focused on external boundaries; avoid over-mocking internal logic.
