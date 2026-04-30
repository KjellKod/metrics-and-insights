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
    classify_external_ci_signal,
    configured_agentic_patterns,
    emit_report,
    filter_repositories,
    format_responsible_people,
    merge_external_ci_evidence,
    load_token,
    parse_patterns,
    parse_csv_values,
    render_table,
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


def test_rust_lint_and_integration_patterns_count_toward_score() -> None:
    workflows = [
        {
            "path": ".github/workflows/rust-ci.yml",
            "text": """
name: Rust CI
jobs:
  rust:
    steps:
      - name: Format check
        run: cargo fmt --all -- --check
      - name: Clippy
        run: cargo clippy --workspace --all-targets --all-features -- -D warnings
      - name: Unit tests
        run: cargo test --workspace --all-features
      - name: Integration tests
        run: cargo test --tests --workspace --all-features
""",
        }
    ]

    score, grade, evidence = score_workflows(workflows)

    assert score == 3
    assert grade == "strong"
    assert evidence["linter"]
    assert evidence["unit_tests"]
    assert evidence["smoke_integration_tests"]


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


def test_tool_specific_workflow_counts_as_agentic_ci_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("CI_MATURITY_AGENTIC_PATTERNS", "example-review-action")
    workflows = [
        {
            "path": ".github/workflows/frontend-review.yml",
            "text": """
name: Frontend / UX Review
jobs:
  frontend-review:
    steps:
      - name: AI frontend review
        uses: example/example-review-action@v1
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


def test_active_ci_true_when_recent_external_ci_signal_exists_without_workflows() -> None:
    now = datetime(2026, 4, 30, tzinfo=timezone.utc)
    external_latest_at = now - timedelta(hours=4)

    status, reason = active_ci_status([], None, 90, now, external_latest_at)

    assert status is True
    assert reason == "latest_external_ci_within_90_days"


def test_atlantis_status_counts_as_external_terraform_integration_ci() -> None:
    signal = classify_external_ci_signal(
        "commit status",
        pull_number=341,
        name="atlantis/plan: infra/nonproduction/lambda/default",
        description="Plan failed.",
        state="failure",
        url="http://atlantis.internal/jobs/1",
        updated_at="2026-04-29T17:15:41Z",
    )
    _, _, evidence = score_workflows([])

    merged = merge_external_ci_evidence(evidence, [signal])

    assert signal == {
        "category": "smoke_integration_tests",
        "evidence": "commit status: PR #341: atlantis/plan: infra/nonproduction/lambda/default (failure)",
        "updated_at": "2026-04-29T17:15:41Z",
        "url": "http://atlantis.internal/jobs/1",
    }
    assert merged["smoke_integration_tests"] == [
        "commit status: PR #341: atlantis/plan: infra/nonproduction/lambda/default (failure)"
    ]


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


class StubGitHubClient(GitHubClient):
    def __init__(self, payloads: dict[str, object]) -> None:
        super().__init__("token")
        self.payloads = payloads

    def get_json(self, path_or_url: str, *, params: dict[str, object] | None = None) -> object:
        if path_or_url.endswith("/pulls"):
            return self.payloads["pulls"]
        if "/commits/" in path_or_url:
            return self.payloads["commit"]
        if path_or_url.startswith("/users/"):
            login = path_or_url.rsplit("/", 1)[1]
            return self.payloads["users"][login]
        raise AssertionError(f"unexpected request: {path_or_url}")


def test_recent_merged_pr_authors_returns_distinct_recent_people_with_names() -> None:
    client = StubGitHubClient(
        {
            "pulls": [
                {
                    "number": 5,
                    "title": "open",
                    "merged_at": None,
                    "html_url": "https://github.test/pr/5",
                    "user": {"login": "ignored", "html_url": "https://github.test/ignored"},
                },
                {
                    "number": 4,
                    "title": "latest api change",
                    "merged_at": "2026-04-28T10:00:00Z",
                    "html_url": "https://github.test/pr/4",
                    "user": {"login": "KjellKod", "html_url": "https://github.test/KjellKod"},
                },
                {
                    "number": 3,
                    "title": "second change",
                    "merged_at": "2026-04-27T10:00:00Z",
                    "html_url": "https://github.test/pr/3",
                    "user": {"login": "teammate", "html_url": "https://github.test/teammate"},
                },
                {
                    "number": 2,
                    "title": "older duplicate",
                    "merged_at": "2026-04-26T10:00:00Z",
                    "html_url": "https://github.test/pr/2",
                    "user": {"login": "KjellKod", "html_url": "https://github.test/KjellKod"},
                },
            ],
            "users": {
                "KjellKod": {"name": "Kjell Hedstrom", "html_url": "https://github.test/KjellKod"},
                "teammate": {"name": "", "html_url": "https://github.test/teammate"},
            },
        }
    )

    authors = client.recent_merged_pr_authors("KjellKod", "metrics-and-insights", responsible_count=2, scan_limit=30)

    assert authors == [
        {
            "login": "KjellKod",
            "name": "Kjell Hedstrom",
            "url": "https://github.test/KjellKod",
            "latest_merged_pr": {
                "number": 4,
                "title": "latest api change",
                "merged_at": "2026-04-28T10:00:00Z",
                "url": "https://github.test/pr/4",
            },
        },
        {
            "login": "teammate",
            "name": "",
            "url": "https://github.test/teammate",
            "latest_merged_pr": {
                "number": 3,
                "title": "second change",
                "merged_at": "2026-04-27T10:00:00Z",
                "url": "https://github.test/pr/3",
            },
        },
    ]


def test_latest_commit_date_returns_default_branch_commit_day() -> None:
    client = StubGitHubClient(
        {
            "commit": {
                "commit": {
                    "committer": {"date": "2026-04-29T17:15:08Z"},
                    "author": {"date": "2026-04-28T12:00:00Z"},
                }
            }
        }
    )

    assert client.latest_commit_date("onfleet", "terraform", "main") == "2026-04-29"


def test_format_responsible_people_includes_public_name_when_available() -> None:
    people = [{"login": "KjellKod", "name": "Kjell Hedstrom"}, {"login": "teammate", "name": ""}]

    assert format_responsible_people(people) == "KjellKod (Kjell Hedstrom), teammate"
    assert format_responsible_people([]) == "unknown"


def test_parser_does_not_embed_owner_env_value_in_default(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_METRIC_OWNER_OR_ORGANIZATION", "KjellKod")

    args = build_argument_parser().parse_args([])

    assert not hasattr(args, "owner")


def test_help_output_includes_filtering_and_responsibility_examples(capsys) -> None:
    try:
        build_argument_parser().parse_args(["--help"])
    except SystemExit as exc:
        assert exc.code == 0

    help_text = capsys.readouterr().out
    assert "archived-*,*-other,*-sandbox" in help_text
    assert "count 3" in help_text
    assert "scan-limit 50" in help_text
    assert "\nExamples:" not in help_text


def test_load_token_uses_configured_env_var(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN_READONLY_WEB", " test-token ")

    assert load_token("GITHUB_TOKEN_READONLY_WEB") == "test-token"


def test_json_output_includes_score_evidence_skipped_and_rate_limit_metadata(tmp_path: Path) -> None:
    report = {
        "owner": "example",
        "active_days": 90,
        "cached_result_count": 0,
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
                "last_commit": "2026-04-29",
                "workflow_file_count": 2,
                "responsible_people": [{"login": "KjellKod", "name": "Kjell Hedstrom"}],
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
    assert payload["repositories"][0]["last_commit"] == "2026-04-29"
    assert payload["repositories"][0]["evidence"]["agentic_ci"]
    assert payload["repositories"][0]["responsible_people"][0]["login"] == "KjellKod"
    assert payload["skipped"] == [{"name": "legacy", "reason": "archived"}]
    assert payload["rate_limit_events"][0]["slept_seconds"] == 7.0


def test_table_output_includes_responsible_people() -> None:
    report = {
        "owner": "KjellKod",
        "repository_count": 1,
        "cached_result_count": 2,
        "skipped": [],
        "repositories": [
            {
                "name": "KjellKod/metrics-and-insights",
                "score": 4,
                "grade": "top",
                "active_ci": True,
                "last_commit": "2026-04-29",
                "responsible_people": [{"login": "KjellKod", "name": "Kjell Hedstrom"}],
            }
        ],
    }

    rendered = render_table(report)

    assert "Legend: score is 0-4, with 1 point each for linter" in rendered
    assert "Authors are recent merged PR authors to help route follow-up, not assigned owners." in rendered
    assert "recent merged PR authors" in rendered
    assert "last commit" in rendered
    assert "2026-04-29" in rendered
    assert "KjellKod (Kjell Hedstrom)" in rendered
    assert "Re-run with --force-fresh" in rendered


def test_csv_output_has_category_booleans() -> None:
    report = {
        "cached_result_count": 1,
        "repositories": [
            {
                "name": "example/api",
                "score": 1,
                "grade": "basic",
                "active_ci": True,
                "active_ci_reason": "latest_run_within_90_days",
                "latest_workflow_run_at": "2026-04-28T00:00:00Z",
                "last_commit": "2026-04-29",
                "workflow_file_count": 1,
                "responsible_people": [{"login": "KjellKod", "name": "Kjell Hedstrom"}],
                "evidence": {
                    "linter": [],
                    "unit_tests": [],
                    "smoke_integration_tests": [],
                    "agentic_ci": ["ai-review.yml: example/review-agent-action"],
                },
            }
        ],
    }
    output = io.StringIO()

    from git_metrics.ci_maturity_report import render_csv

    render_csv(report, output)

    assert "agentic_ci" in output.getvalue()
    assert "last_commit" in output.getvalue()
    assert "responsible_people" in output.getvalue()
    assert "cached_result_count" in output.getvalue()
    assert "KjellKod (Kjell Hedstrom)" in output.getvalue()
    assert "2026-04-29" in output.getvalue()
    assert "True" in output.getvalue()
