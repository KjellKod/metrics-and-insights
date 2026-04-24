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
  - default to previous calendar year for the baseline period and current calendar year for the focus period when the user does not specify overrides
  - confirm exact dates when the user uses relative language like "this year" or "since February"
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
  - one tab per team from runtime team metadata
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
3. Read non-secret config from `.env` when needed:
   - `GITHUB_METRIC_OWNER_OR_ORGANIZATION`
   - `GITHUB_METRIC_REPO`
   - `GITHUB_REPO_FOR_PR_TRACKING`
4. If repos were not explicitly provided by the user, resolve them from `.env`, show the exact list to the user, and require confirmation before collecting GitHub data.
5. If the repo list is wrong, instruct the user to update the env variable(s) and restart the prompt after the env file is corrected.
6. Keep secrets out of logs and final answers.
7. Use the committed repo-confirmation script before the build:

```bash
python3 scripts/engineering_throughput_show_config.py \
  --jira-csv-dir <jira-csv-dir> \
  [--team-config <team-config.json>] \
  --spreadsheet-mode <create|update> \
  [--spreadsheet-id <sheet-id>] \
  [--repos <repo1,repo2>] \
  [--focus-start <YYYY-MM-DD>] \
  [--date-end <YYYY-MM-DD>]
```

### 2. Collect Jira Metrics

For each requested team source and each requested year:

```bash
python3 jira_metrics/individual.py --year <baseline_year> -team "<team dropdown value>" -csv
python3 jira_metrics/individual.py --year <focus_year> -project "<project key>" -csv
```

Move generated CSVs into the run directory immediately if they land in the repo root.

Create a runtime team config JSON for the committed build when team tabs are needed:

```json
{
  "teams": [
    {
      "name": "Example Team",
      "jira_csv": "example_individual_metrics.csv",
      "repos": ["example-repo"]
    }
  ]
}
```

Rules:

- `name` and `jira_csv` are required
- `repos` is optional and is only used for team-scoped GitHub context
- if team tabs are not needed, skip the team config and pass only `--jira-csv-dir`; the committed build will produce a global Jira summary without team tabs

### 3. Collect and Summarize GitHub Metrics

Use the requested GitHub repositories. If none are provided, resolve configured repos from `.env`, show the exact repo list to the user, and wait for confirmation before proceeding.

Use the committed build entrypoint for GitHub collection, Jira summarization, and payload generation:

```bash
python3 scripts/engineering_throughput_build.py \
  --jira-csv-dir <jira-csv-dir> \
  [--team-config <team-config.json>] \
  --spreadsheet-mode <create|update> \
  [--spreadsheet-id <sheet-id>] \
  [--repos <repo1,repo2>] \
  [--exclude-config <exclude-config.json>] \
  [--focus-start <YYYY-MM-DD>] \
  [--date-end <YYYY-MM-DD>] \
  [--out-dir .ws/engineering-throughput-<YYYY-MM-DD>]
```

The committed build:

- validates repo access explicitly
- collects merged PR detail rows by repo and month
- stores raw PR detail locally as `github_metrics_payload.json`
- keeps raw throughput metrics visible
- applies optional exclusion rules only to process-eligible metrics
- writes:
  - `run_config.json`
  - `github_metrics_payload.json`
  - `github_summary.json`
  - `jira_summary.json`
  - `sheet_payload.json`

Use `exclude-config.json` only for special cases that distort process interpretation. First-pass schema:

```json
{
  "windows": [
    {"name": "hackathon", "start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}
  ],
  "rules": [
    {
      "reason": "release-promotion",
      "repos": ["example-repo"],
      "authors": ["release-bot"],
      "title_contains": ["release"]
    }
  ]
}
```

### 4. Google Sheets MCP

Use the Google Sheets MCP connector for spreadsheet operations.

Typical sequence:

1. `gs_drive_create_spreadsheet` when mode is `create`
2. `gs_write_create_sheet` for each tab in `sheet_payload.json`
3. `gs_write_values_batch_update` using the bounded ranges from `sheet_payload.json`
4. `gs_chart_create` for charts
5. `gs_write_set_column_width` and `gs_write_format_cells` for readability
6. `gs_read_values_*` and `gs_chart_list` to verify

If the MCP transport closes, do not work around it by dumping huge payloads. First compact the data further, then retry when the MCP is available.

### 5. Verification

Before final response:

- Run targeted tests if code changed, especially:
  - `python3 -m unittest jira_metrics.tests.test_individual`
  - `python3 -m pytest tests/unit/engineering_throughput`
  - `python3 -m pytest tests/integration/test_engineering_throughput_build.py`
- Read back key ranges from:
  - `Jira Summary`
  - `GitHub Summary`
  - `Recommendations`
  - at least one Jira team tab when a team config was used
- Run `gs_chart_list` and confirm expected charts exist.
- Report the spreadsheet URL, tabs created, chart count, local raw-data path, tests run, and any caveats.
