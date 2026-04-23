---
name: engineering-throughput-spreadsheet
description: Create or refresh the engineering throughput Google Sheet from Jira individual metrics and GitHub PR activity, including team tabs, Jira/GitHub summary tabs, charts, adjusted GitHub process metrics, repo confirmation, and executive/team recommendations.
---

# Engineering Throughput Spreadsheet

Use this skill when the user asks to create, refresh, or analyze an engineering throughput spreadsheet from this repo's Jira and GitHub metrics scripts.

## Intake

Do not hardcode team names. Do not include specific team names or individual names as examples in this skill. Ask for or infer the minimum required inputs:

- team names
- Jira source for each team:
  - `-team <Jira Team[Dropdown] value>`
  - or `-project <Jira project key>`
- time range:
  - default to `2025` through the current year only if the user has not specified a range
  - confirm exact years when the user uses relative language like "this year" or "since February"
- GitHub repositories:
  - prefer explicit user input
  - otherwise read non-secret repo config from `.env`
  - never silently assume repo coverage
  - if repos are resolved from `.env`, always tell the user the exact repo list before collection and ask for confirmation
- spreadsheet mode:
  - create a new spreadsheet
  - or refresh/update an existing spreadsheet ID

If the user provides team names but not Jira source mappings, make conservative guesses from repo conventions and call out the assumptions before collecting data.

If GitHub repos are not explicitly provided, resolve them from `.env` and say:

`These are the repos I am using: <repo list>. If correct, continue (y). If not, please update the env variable(s) and restart this prompt once they are updated.`

Use `GITHUB_METRIC_REPO` and `GITHUB_REPO_FOR_PR_TRACKING` as the source of truth for repo coverage unless the user overrides them directly in the prompt.

## Defaults

- Work files: store all raw JSON, CSV, and generated payloads under `.ws/engineering-throughput-<YYYY-MM-DD>/`.
- Spreadsheet tabs:
  - `Recommendations`
  - `Jira Summary`
  - one tab per team
  - `GitHub Summary`
  - `GitHub No Approval`
  - `GitHub Repos`
  - `GitHub Authors`
  - `GitHub Flags`
- Do not push raw PR dumps into Google Sheets. Keep raw data locally and push compact insight tables only.

## Workflow

### 1. Prepare

1. Inspect repo-local skills and obey `AGENTS.md`.
2. Create a run directory under `.ws/`.
3. Check `jira_metrics/individual.py` supports `--year`. If not, add it before collecting data.
4. Read non-secret config from `.env` when needed:
   - `GITHUB_METRIC_OWNER_OR_ORGANIZATION`
   - `GITHUB_METRIC_REPO`
   - `GITHUB_REPO_FOR_PR_TRACKING`
   - `GITHUB_REPO_FOR_RELEASE_TRACKING`
5. If repos were not explicitly provided by the user, resolve them from `.env`, show the exact list to the user, and require confirmation before collecting GitHub data.
6. If the repo list is wrong, instruct the user to update the env variable(s) and restart the prompt after the env file is corrected.
7. Keep secrets out of logs and final answers.

### 2. Collect Jira Metrics

For each requested team source and each requested year:

```bash
python3 jira_metrics/individual.py --year 2025 -team "<team dropdown value>" -csv
python3 jira_metrics/individual.py --year 2026 -project "<project key>" -csv
```

If `individual.py` writes CSVs to the repo root, move them into the `.ws/` run directory immediately.

Parse the CSV sections:

- `Assignee Released Points`
- `Assignee Released Tickets`

Create a compact `Jira Summary` tab that shows:

- all-team 2025 monthly average vs 2026 focus-period monthly average
- completed tickets
- completed points
- points per completed ticket
- team-by-team deltas vs the 2025 average
- a monthly all-team trend table and charts

For each team tab, write:

- source and generated date
- period comparison: baseline monthly average, first focus month, focus-period monthly average, delta vs baseline
- monthly team totals
- individual points by month
- individual tickets by month
- chart helper ranges for top contributors

Create charts per team:

- team monthly totals
- top individual points
- top individual tickets

### 3. Collect GitHub Metrics

Use the requested GitHub repositories. If none are provided, resolve configured repos from `.env`, show the exact repo list to the user, and wait for confirmation before proceeding.

Prefer GitHub GraphQL search by repo/month because REST per-PR calls are too slow for high-volume repos. Collect merged PRs for the requested date range.

For each PR, capture:

- month, repo, PR number, title, URL
- author
- created and merged timestamps
- hours to merge
- hours to first review
- hours to first approval
- additions, deletions, changed files, total lines changed
- review count and approval count
- flags:
  - large PR: `lines_changed > 1000`
  - slow merge: `hours_to_merge > 72`
  - no approval: `approval_count == 0`

Store raw PR detail locally as `.ws/.../github_metrics_payload.json`.

Separate raw throughput metrics from process-eligible metrics:

- raw throughput includes all merged PRs
- process-eligible metrics exclude special-case PRs that distort process interpretation
- examples of special cases include release-promotion PRs and user-specified hackathon or experiment windows

Keep raw throughput visible. Use process-eligible metrics for PR-size, approval-latency, slow-merge, and no-approval analysis.

### 4. Compact GitHub Analysis

Only write compact analysis to the spreadsheet:

`GitHub Summary`
- baseline vs focus-period comparison
- raw throughput and process-eligible throughput side by side
- delta and percent change
- monthly trend table
- chart helper ranges for PR count, merge latency, and risk rates

`GitHub No Approval`
- adjusted no-approval list for counted PRs
- excluded false-positive summary
- compact list of excluded release-promotion / hackathon / experiment PRs for auditability

`GitHub Repos`
- repo-level baseline vs focus-period metrics

`GitHub Authors`
- top increases, top decreases, and current high-volume authors
- note that GitHub logins are not Jira team identities unless an explicit mapping exists

`GitHub Flags`
- top flagged authors
- a small PR sample, not the full raw dump

Create charts:

- GitHub PR count and merge latency
- GitHub PR risk rates
- top GitHub authors by merged or eligible PRs

### 5. Recommendations

Write recommendations to a dedicated `Recommendations` tab. Use the data as a management signal, not as a verdict on people.

Include:

- Executive readout for CTO, EMs, and PMs
- Team manager recommendations for every team
- 30-day experiments
- suggested improvement goals / EM scorecard

Use this framing:

- AI tools can increase implementation speed faster than agile/scrum ceremonies adapt.
- Combine Jira and GitHub signals when explaining the pattern.
- Expect implementation speed to rise before review, planning, and acceptance processes adapt.
- Keep improvements where throughput improved.
- Treat large PRs as the main anti-pattern unless quality data says otherwise.
- Do not overreact to no-approval PRs; they may represent AI-assisted solo work or AI-review paths. Recommend explicit labels/policy so the metric becomes interpretable.
- Explain "flow control" concretely: WIP limits, daily review-queue sweeps, same-business-day review for small PRs, mid-sprint acceptance slices, and explicit expedite lanes.
- Before calling out an individual as needing coaching, caveat capacity changes, team moves, support load, and assignment mix.

Recommended experiment themes:

- small-PR lane
- explicit `AI-assisted`, `AI-reviewed`, and `human-review-required` labels
- same-business-day review target for small PRs
- mid-sprint acceptance slices
- team AI workflow reviews

Suggested improvement goals should be practical and phased:

- current baseline
- Q2 target
- Q3 target
- Q4 idea or stretch direction

Prefer goals that combine throughput and reviewability, such as:

- median first human approval
- median merge time for normal PRs
- large PR rate
- explicit exception labeling
- sustaining or recovering Jira ticket throughput without compensating via larger PR batches

### 6. Google Sheets MCP

Use the Google Sheets MCP connector for spreadsheet operations.

Typical sequence:

1. `gs_drive_create_spreadsheet`
2. `gs_write_create_sheet` for each tab
3. `gs_write_values_batch_update` for compact table writes
4. `gs_chart_create` for charts
5. `gs_write_set_column_width` and `gs_write_format_cells` for readability
6. `gs_read_values_*` and `gs_chart_list` to verify

If the MCP transport closes, do not work around it by dumping huge payloads. First compact the data further, then retry when the MCP is available.

### 7. Verification

Before final response:

- Run targeted tests if code changed, especially `python3 -m unittest jira_metrics.tests.test_individual`.
- Read back key ranges from:
  - `Jira Summary`
- Read back key ranges from:
  - `GitHub Summary`
  - `Recommendations`
  - at least one Jira team tab
- Run `gs_chart_list` and confirm expected charts exist.
- Report the spreadsheet URL, tabs created, chart count, local raw-data path, tests run, and any caveats.
