# Quest Journal: Quest Brief

- Quest ID: `generic-throughput-scripts_2026-04-23__1735`
- Completed: 2026-04-23
- Mode: workflow
- Quality: Tin
- Outcome: Promote the useful logic from the local `.ws` scripts into committed, reusable repo code that is: - team agnostic - company agnostic - person agnostic - year agnostic while leaving the `.ws` origin...

## What Shipped

**Problem**: Useful throughput logic currently lives in local `.ws` scripts that are not reusable and still encode year-specific labels and company-specific narrative. The repo needs committed, generic code that can collect GitHub throughput data, summarize existing Jira CSV outputs, assemble Goo...

## Files Changed

- `.quest/generic-throughput-scripts_2026-04-23__1735/phase_01_plan/plan.md`
- `.quest/generic-throughput-scripts_2026-04-23__1735/phase_01_plan/arbiter_verdict.md`
- `.quest/generic-throughput-scripts_2026-04-23__1735/phase_01_plan/review_findings.json`
- `.quest/generic-throughput-scripts_2026-04-23__1735/phase_01_plan/review_backlog.json`
- `.quest/generic-throughput-scripts_2026-04-23__1735/phase_01_plan/review_plan-reviewer-a.md`
- `.quest/generic-throughput-scripts_2026-04-23__1735/phase_01_plan/review_plan-reviewer-b.md`
- `.quest/generic-throughput-scripts_2026-04-23__1735/phase_02_implementation/pr_description.md`
- `.quest/generic-throughput-scripts_2026-04-23__1735/phase_02_implementation/builder_feedback_discussion.md`
- `.quest/generic-throughput-scripts_2026-04-23__1735/phase_03_review/review_code-reviewer-a.md`
- `.quest/generic-throughput-scripts_2026-04-23__1735/phase_03_review/review_findings_code-reviewer-a.json`
- `.quest/generic-throughput-scripts_2026-04-23__1735/phase_03_review/review_code-reviewer-b.md`
- `.quest/generic-throughput-scripts_2026-04-23__1735/phase_03_review/review_findings_code-reviewer-b.json`
- `.quest/generic-throughput-scripts_2026-04-23__1735/phase_03_review/review_fix_feedback_discussion.md`

## Iterations

- Plan iterations: 1
- Fix iterations: 4

## Agents

- **The Judge** (arbiter): 
- **The Implementer** (builder): 

## Quest Brief

Promote the useful logic from the local `.ws` scripts into committed, reusable repo code that is:

- team agnostic
- company agnostic
- person agnostic
- year agnostic

while leaving the `.ws` originals unchanged as the baseline reference.

Baseline local sources:

- `.ws/github-throughput-2025-2026-expanded/collect_github_metrics.py:1`
- `.ws/github-throughput-2025-2026-expanded/build_sheet_payload.py:1`

Out of scope for first pass:

- perfect Jira<->GitHub identity mapping
- rebuilding existing Jira team tab logic from scratch
- embedding team/person-specific recommendation prose in committed code
- putting MCP-specific Google Sheets API logic into committed repo code

Acceptance Criteria

1. No committed script contains hardcoded team names, individual names, org-specific prose, or fixed year strings.
2. Default window is previous year + current year, with CLI overrides.
3. Resolved GitHub repos come from CLI or env, can be printed for confirmation, and are not silently assumed.
4. Fixed tab names are allowed, but year labels and comparison labels are generated at runtime.
5. Team names, repo groups, and author names appear only as runtime data.
6. New committed scripts can generate a brand new spreadsheet payload and support creating a new sheet successfully through the skill.
7. The skill is updated to use the new committed scripts, not `.ws` scripts.
8. The `.ws` originals remain untouched.

Architecture

Use the repo's existing structure:

```text
git_metrics/
  throughput_collect.py
  throughput_summary.py

jira_metrics/
  throughput_summary.py

engineering_throughput/
  __init__.py
  config.py
  date_ranges.py
  models.py
  github_payload.py
  jira_payload.py
  recommendations.py
  sheet_builder.py

scripts/
  engineering_throughput_build.py
  engineering_throughput_show_config.py
```

Why this layout

- `git_metrics/` holds GitHub collection and GitHub-specific summarization
- `jira_metrics/` holds Jira summarization built on existing Jira scripts/data
- `engineering_throughput/` holds cross-source composition and generic sheet logic
- `scripts/` stays thin and operational, consistent with repo structure

Concrete File Plan

### `git_metrics/throughput_collect.py`

- Purpose: generic merged-PR collector
- Source: adapted from `.ws/.../collect_github_metrics.py`
- Responsibilities:
  - read owner/repos from args or env
  - validate repos
  - collect merged PRs by month
  - calculate raw PR row fields
  - emit raw JSON payload
- Must not:
  - contain spreadsheet tab logic
  - contain recommendation prose
  - contain fixed year assumptions beyond defaults in config

### `git_metrics/throughput_summary.py`

- Purpose: GitHub-only summarization
- Responsibilities:
  - period metrics
  - monthly trends
  - repo comparison
  - author comparison
  - flagged authors / flagged PR sample
  - raw vs process-eligible metrics
  - special-case exclusion application from config
- Output:
  - generic summary objects, not sheet cell ranges

### `jira_metrics/throughput_summary.py`

- Purpose: generic Jira throughput summary from existing team CSV output
- Responsibilities:
  - parse `individual.py --csv` output artifacts
  - calculate team monthly totals
  - compute all-team monthly totals
  - compute baseline vs focus comparison
  - compute points-per-ticket summary
- Must reuse existing Jira sources rather than reimplement Jira fetching

### `engineering_throughput/config.py`

- Purpose: runtime config resolution
- Responsibilities:
  - parse CLI args
  - resolve env fallback
  - resolve years
  - resolve repo list
  - resolve optional team metadata file
  - write `.ws/<run>/run_config.json`
- Core dataclasses:
  - `RunConfig`
  - `DateWindowConfig`
  - `RepoConfig`
  - `TeamConfig`

### `engineering_throughput/date_ranges.py`

- Purpose: dynamic year and focus label logic
- Responsibilities:
  - compute baseline year = previous year by default
  - compute focus year = current year by default
  - derive start, end, focus_start, focus_end
  - generate labels like:
    - `2025 baseline`
    - `2026 YTD`
    - `2026 Feb-Apr`
- No fixed strings like `2025 vs 2026 Feb-Apr`

### `engineering_throughput/models.py`

- Purpose: shared data structures
- Likely models:
  - `PeriodComparison`
  - `MonthlySeries`
  - `GitHubSummary`
  - `JiraSummary`
  - `SheetSection`
  - `SheetPayload`

### `engineering_throughput/github_payload.py`

- Purpose: turn GitHub summary objects into generic tab tables
- Responsibilities:
  - `GitHub Summary`
  - `GitHub No Approval`
  - `GitHub Repos`
  - `GitHub Authors`
  - `GitHub Flags`
- Must compute table sizes dynamically
- Must not hardcode cell ranges like `A1:O80`

### `engineering_throughput/jira_payload.py`

- Purpose: turn Jira summary objects into generic tab tables
- Responsibilities:
  - `Jira Summary`
  - team tabs from runtime team metadata and parsed Jira outputs
- Team tab names can be data-driven from config/runtime

### `engineering_throughput/recommendations.py`

- Purpose: generic recommendation and goal generation
- Responsibilities:
  - generic executive observations based on metrics
  - generic process guidance
  - generic improvement goals
  - optional team-level recommendations from team metrics without embedded team/person names in code
- Important rule:
  - recommendations come from heuristics/templates, not hardcoded team/person prose

### `engineering_throughput/sheet_builder.py`

- Purpose: combine Jira + GitHub payload sections into a single sheet payload
- Responsibilities:
  - compute ranges from table sizes
  - define tabs to create/update
  - assemble payload for skill/MCP layer
- Important rule:
  - this module builds payload only
  - it does not call MCP directly

### `scripts/engineering_throughput_show_config.py`

- Purpose: print resolved runtime config before live run
- Output:
  - owner
  - repo list
  - years
  - focus period
  - team config source
  - output dir
- This supports the repo confirmation flow

### `scripts/engineering_throughput_build.py`

- Purpose: main thin entrypoint
- Responsibilities:
  - parse args
  - call config resolution
  - collect GitHub data
  - summarize Jira
  - summarize GitHub
  - build payload JSON
  - write artifacts to `.ws/<run>/...`

## Carry-Over Findings

- No carry-over findings this round; nothing was inherited from earlier quests and nothing needs to be saved for the next one.

## Celebration

This journal embeds the celebration payload used by `/celebrate`.

- [Jump to Celebration Data](#celebration-data)
- Replay locally: `/celebrate docs/quest-journal/generic-throughput-scripts_2026-04-23.md`

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
      "desc": "Tackled 17 review findings"
    },
    {
      "icon": "[TEST]",
      "title": "Battle Tested",
      "desc": "Survived 5 reviews"
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
      "label": "Plan iterations: 1"
    },
    {
      "icon": "🔧",
      "label": "Fix iterations: 4"
    },
    {
      "icon": "📝",
      "label": "Review findings: 5"
    }
  ],
  "quality": {
    "tier": "Tin",
    "grade": "T"
  },
  "inherited_findings_used": {
    "count": 0,
    "summaries": []
  },
  "findings_left_for_future_quests": {
    "count": 0,
    "summaries": []
  },
  "test_count": null,
  "tests_added": null,
  "files_changed": 13
}
```
<!-- celebration-data-end -->
