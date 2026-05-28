# Quest Journal: Development Time Jira Metrics

- Quest ID: `development-time-jira-metrics_2026-05-26__1620`
- Slug: development-time-jira-metrics
- Completed: 2026-05-27
- Mode: workflow
- Quality: Gold
- Celebration: [`celebrations/development-time-jira-metrics_2026-05-27.md`](celebrations/development-time-jira-metrics_2026-05-27.md)
- Outcome: Add a Development Time Jira metrics script. Goal: Create a new Jira metrics report for Development Time without changing the existing cycle time behavior. Definition: Development Time is measured f...

## What Shipped

**Problem**: The repo has `jira_metrics/cycle_time.py` for code-review-to-release metrics, but no report for Development Time as defined by the first transition into `In Progress` and the immediately following Jira status transition.

**Impact**: Teams can inspect how long tickets spend in their ...

## Files Changed

- `metrics-and-insights/.quest/development-time-jira-metrics_2026-05-26__1620/phase_01_plan/plan.md`
- `metrics-and-insights/.quest/development-time-jira-metrics_2026-05-26__1620/phase_01_plan/arbiter_verdict.md.next`
- `metrics-and-insights/.quest/development-time-jira-metrics_2026-05-26__1620/phase_01_plan/review_findings.json.next`
- `metrics-and-insights/.quest/development-time-jira-metrics_2026-05-26__1620/phase_01_plan/review_plan-reviewer-a.md`
- `metrics-and-insights/.quest/development-time-jira-metrics_2026-05-26__1620/phase_01_plan/review_plan-reviewer-b.md`
- `metrics-and-insights/.quest/development-time-jira-metrics_2026-05-26__1620/phase_02_implementation/pr_description.md`
- `metrics-and-insights/.quest/development-time-jira-metrics_2026-05-26__1620/phase_02_implementation/builder_feedback_discussion.md`
- `metrics-and-insights/.quest/development-time-jira-metrics_2026-05-26__1620/phase_03_review/review_code-reviewer-a.md`
- `metrics-and-insights/.quest/development-time-jira-metrics_2026-05-26__1620/phase_03_review/review_findings_code-reviewer-a.json`
- `metrics-and-insights/.quest/development-time-jira-metrics_2026-05-26__1620/phase_03_review/review_code-reviewer-b.md`
- `metrics-and-insights/.quest/development-time-jira-metrics_2026-05-26__1620/phase_03_review/review_findings_code-reviewer-b.json`

## Iterations

- Plan iterations: 2
- Fix iterations: 0

## Agents

- **The Judge** (arbiter): 
- **The Implementer** (builder): 

## Quest Brief

Add a Development Time Jira metrics script.

Goal:
Create a new Jira metrics report for Development Time without changing the existing cycle time behavior.

Definition:
Development Time is measured from the first Jira status transition into `In Progress` to the immediately next Jira status transition after that, whatever that next status is.

Important behavior:
- Match `In Progress` case-insensitively.
- Only measure the first matching range per ticket.
- Example: `In Progress -> Blocked -> In Progress -> Code Review` measures only `In Progress -> Blocked`; the second `In Progress -> Code Review` range is not measured in v1.
- If a ticket never enters `In Progress`, skip it.
- If a ticket enters `In Progress` but has no later status transition, skip it.
- Do not add configurable start/end status lists in v1. That is explicitly out of scope/YAGNI.

Reporting:
Produce monthly metrics for:
- Organization-wide `All`
- Team breakdowns when team data is available
- If team field is missing/unset, group as `<PROJECT>/unknown-team`

Metrics per month/group:
- Median Development Time (days)
- P75 Development Time (days)
- Ticket Count
- Skipped: missing in-progress
- Skipped: no next status after in-progress

Time calculation:
Use the same business-time convention as existing cycle time:
- Monday-Friday only
- capped at 8 hours per weekday
- business days = business seconds / (3600 * 8)
- no holiday calendar and no fixed 9-5 office window

Filtering:
Add a new script, likely `jira_metrics/development_time.py`.
The script must require issue types at runtime and refuse to run if they are not provided.

Example CLI:
`python3 jira_metrics/development_time.py --issue-types Story,Task,Bug`
`python3 jira_metrics/development_time.py --issue-types Bug`

Only report data for the provided issue types. Do not add an issue-type breakdown in v1.

Architecture:
Keep existing `jira_metrics/cycle_time.py` behavior intact.
Prefer extracting a small shared helper if it reduces duplication safely, especially for:
- ordered Jira status transition extraction
- business-time calculation reuse
- generic status-window measurement

But keep the change narrow. Do not broadly refactor Jira metrics scripts.

Acceptance criteria:
- Existing cycle time tests still pass unchanged.
- New tests cover:
  - first `In Progress` to immediate next status
  - repeated `In Progress` ranges only count the first range
  - missing `In Progress` skip count
  - `In Progress` with no later status skip count
  - case-insensitive `In Progress`
  - required `--issue-types`
  - team fallback to `<PROJECT>/unknown-team`
  - median and P75 calculations
- README or relevant docs mention the new script and CLI usage.
- Follow repo principles: KISS, YAGNI, SRP, DRY, strong typing where practical, focused tests, no unrelated refactors.

## Findings Left For Future Quests

- Count: **1**
- Project keys interpolated into JQL unquoted while issue types are escaped

## Celebration

This journal embeds the celebration payload used by `/celebrate`.

- Full celebration: [`celebrations/development-time-jira-metrics_2026-05-27.md`](celebrations/development-time-jira-metrics_2026-05-27.md)
- [Jump to Celebration Data](#celebration-data)
- Replay locally: `/celebrate docs/quest-journal/development-time-jira-metrics_2026-05-27.md`

## Celebration Data

<!-- celebration-data-start -->
```json
{
  "quest_mode": "workflow",
  "agents": [
    {
      "name": "arbiter",
      "model": "",
      "role": "The Judge"
    },
    {
      "name": "builder",
      "model": "",
      "role": "The Implementer"
    }
  ],
  "achievements": [
    {
      "icon": "[BUG]",
      "title": "Gremlin Slayer",
      "desc": "Tackled 18 review findings"
    },
    {
      "icon": "[TEST]",
      "title": "Battle Tested",
      "desc": "Survived 4 reviews"
    },
    {
      "icon": "[PLAN]",
      "title": "Plan Perfectionist",
      "desc": "Iterated plan 2 times"
    },
    {
      "icon": "[WIN]",
      "title": "Quest Complete",
      "desc": "All phases finished successfully"
    }
  ],
  "metrics": [
    {
      "icon": "📊",
      "label": "Plan iterations: 2"
    },
    {
      "icon": "🔧",
      "label": "Fix iterations: 0"
    },
    {
      "icon": "📝",
      "label": "Review findings: 4"
    }
  ],
  "quality": {
    "tier": "Gold",
    "grade": "G"
  },
  "inherited_findings_used": {
    "count": 0,
    "summaries": []
  },
  "findings_left_for_future_quests": {
    "count": 1,
    "summaries": [
      "Project keys interpolated into JQL unquoted while issue types are escaped"
    ]
  },
  "test_count": null,
  "tests_added": null,
  "files_changed": 11
}
```
<!-- celebration-data-end -->
