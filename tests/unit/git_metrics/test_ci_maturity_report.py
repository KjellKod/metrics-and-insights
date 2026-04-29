from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from git_metrics.ci_maturity_report import (
    GitHubClient,
    active_ci_status,
    build_argument_parser,
    configured_agentic_patterns,
    emit_report,
    filter_repositories,
    load_token,
    parse_patterns,
    parse_csv_values,
    score_workflows,
)


def test_parse_repo_filters_accepts_owner_prefixed_and_bare_names() -> None:
    repositories = [
        {"name": "api", "archived": False},
        {"name": "web", "archived": False},
        {"name": "docs", "archived": False},
    ]

    result = filter_repositories(
        repositories,
        excluded_repos=parse_csv_values("Example/api,web"),
        excluded_patterns=[],
        include_archived=False,
    )

    assert [repo["name"] for repo in result.included] == ["docs"]
    assert result.skipped == [
        {"name": "api", "reason": "excluded_repo"},
        {"name": "web", "reason": "excluded_repo"},
    ]


def test_exclude_patterns_match_case_insensitive_repo_names() -> None:
    repositories = [
        {"name": "Archived-Api", "archived": False},
        {"name": "worker-other", "archived": False},
        {"name": "service", "archived": False},
    ]

    result = filter_repositories(
        repositories,
        excluded_repos=set(),
        excluded_patterns=parse_patterns("archived-*,*-other"),
        include_archived=False,
    )

    assert [repo["name"] for repo in result.included] == ["service"]
    assert result.skipped == [
        {"name": "Archived-Api", "reason": "excluded_pattern:archived-*"},
        {"name": "worker-other", "reason": "excluded_pattern:*-other"},
    ]


def test_archived_repos_skipped_by_default() -> None:
    result = filter_repositories(
        [{"name": "legacy", "archived": True}, {"name": "active", "archived": False}],
        excluded_repos=set(),
        excluded_patterns=[],
        include_archived=False,
    )

    assert [repo["name"] for repo in result.included] == ["active"]
    assert result.skipped == [{"name": "legacy", "reason": "archived"}]


def test_score_repo_awards_one_point_per_ci_category() -> None:
    workflows = [
        {
            "path": ".github/workflows/ci.yml",
            "text": """
name: ci
jobs:
  lint:
    steps:
      - run: ruff check .
  unit:
    steps:
      - run: pytest tests/unit
  e2e:
    steps:
      - run: npx playwright test
""",
        }
    ]

    score, grade, evidence = score_workflows(workflows)

    assert score == 3
    assert grade == "strong"
    assert evidence["linter"]
    assert evidence["unit_tests"]
    assert evidence["smoke_integration_tests"]
    assert not evidence["agentic_ci"]


def test_configured_agentic_workflow_counts_as_agentic_ci(monkeypatch) -> None:
    monkeypatch.setenv("CI_MATURITY_AGENTIC_PATTERNS", "review-agent")
    workflows = [
        {
            "path": ".github/workflows/ai-review.yml",
            "text": """
name: AI Review
jobs:
  review:
    steps:
      - uses: example/review-agent-action@v1
""",
        }
    ]

    score, grade, evidence = score_workflows(workflows)

    assert score == 1
    assert grade == "basic"
    assert evidence["agentic_ci"]


def test_agentic_patterns_are_configurable(monkeypatch) -> None:
    monkeypatch.setenv("CI_MATURITY_AGENTIC_PATTERNS", "first-agent,second-agent")

    assert configured_agentic_patterns() == ("first-agent", "second-agent")


def test_active_ci_false_when_no_recent_runs() -> None:
    now = datetime(2026, 4, 28, tzinfo=timezone.utc)
    latest_run = {"updated_at": (now - timedelta(days=120)).isoformat()}

    status, reason = active_ci_status([{"path": "ci.yml", "text": "name: ci"}], latest_run, 90, now)

    assert status is False
    assert reason == "latest_run_older_than_90_days"


def test_rate_limit_wait_uses_retry_after_before_reset_header() -> None:
    sleeps: list[float] = []
    client = GitHubClient("token", sleep_fn=sleeps.append)
    response = requests.Response()
    response.status_code = 429
    response.headers["Retry-After"] = "7"
    response.headers["X-RateLimit-Reset"] = "9999999999"

    client._wait_for_rate_limit(response, "https://api.github.com/test")

    assert sleeps == [7.0]
    assert client.rate_limit_events[0].slept_seconds == 7.0
    assert client.rate_limit_events[0].reset_at is None


def test_parser_does_not_embed_owner_env_value_in_default(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_METRIC_OWNER_OR_ORGANIZATION", "example-owner")

    args = build_argument_parser().parse_args([])

    assert not hasattr(args, "owner")


def test_load_token_uses_configured_env_var(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN_READONLY_WEB", " test-token ")

    assert load_token("GITHUB_TOKEN_READONLY_WEB") == "test-token"


def test_json_output_includes_score_evidence_skipped_and_rate_limit_metadata(tmp_path: Path) -> None:
    report = {
        "owner": "example",
        "active_days": 90,
        "repository_count": 1,
        "skipped": [{"name": "legacy", "reason": "archived"}],
        "repositories": [
            {
                "name": "example/api",
                "score": 4,
                "grade": "top",
                "active_ci": True,
                "active_ci_reason": "latest_run_within_90_days",
                "latest_workflow_run_at": "2026-04-28T00:00:00Z",
                "workflow_file_count": 2,
                "evidence": {
                    "linter": ["ci.yml: ruff check ."],
                    "unit_tests": ["ci.yml: pytest"],
                    "smoke_integration_tests": ["ci.yml: playwright"],
                    "agentic_ci": ["ai-review.yml: example/review-agent-action"],
                },
            }
        ],
        "rate_limit_events": [{"url": "https://api.github.com/test", "slept_seconds": 7.0}],
    }
    output_path = tmp_path / "report.json"

    emit_report(report, output_format="json", output_path=str(output_path))

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["repositories"][0]["score"] == 4
    assert payload["repositories"][0]["evidence"]["agentic_ci"]
    assert payload["skipped"] == [{"name": "legacy", "reason": "archived"}]
    assert payload["rate_limit_events"][0]["slept_seconds"] == 7.0


def test_csv_output_has_category_booleans() -> None:
    report = {
        "repositories": [
            {
                "name": "example/api",
                "score": 1,
                "grade": "basic",
                "active_ci": True,
                "active_ci_reason": "latest_run_within_90_days",
                "latest_workflow_run_at": "2026-04-28T00:00:00Z",
                "workflow_file_count": 1,
                "evidence": {
                    "linter": [],
                    "unit_tests": [],
                    "smoke_integration_tests": [],
                    "agentic_ci": ["ai-review.yml: example/review-agent-action"],
                },
            }
        ]
    }
    output = io.StringIO()

    from git_metrics.ci_maturity_report import render_csv

    render_csv(report, output)

    assert "agentic_ci" in output.getvalue()
    assert "True" in output.getvalue()
