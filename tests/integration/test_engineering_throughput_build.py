from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


FIXTURE_DIR = Path("tests/fixtures/engineering_throughput")


class FakeGitHubClient:
    def validate_repo(self, owner: str, repo: str) -> tuple[bool, str, str]:
        return True, repo.lower(), ""

    def search_merged_prs(self, owner: str, repo: str, window) -> list[dict]:
        fixtures = {
            ("api", "2025-01"): [
                {
                    "number": 1,
                    "title": "baseline api feature",
                    "url": "https://example.com/api/1",
                    "createdAt": "2025-01-02T00:00:00+00:00",
                    "mergedAt": "2025-01-02T08:00:00+00:00",
                    "additions": 40,
                    "deletions": 10,
                    "changedFiles": 3,
                    "author": {"login": "alex"},
                    "reviews": {"nodes": [{"state": "APPROVED", "submittedAt": "2025-01-02T03:00:00+00:00", "author": {"login": "reviewer"}}]},
                }
            ],
            ("web", "2026-02"): [
                {
                    "number": 9,
                    "title": "focus web feature",
                    "url": "https://example.com/web/9",
                    "createdAt": "2026-02-03T00:00:00+00:00",
                    "mergedAt": "2026-02-04T04:00:00+00:00",
                    "additions": 55,
                    "deletions": 15,
                    "changedFiles": 4,
                    "author": {"login": "blair"},
                    "reviews": {"nodes": [{"state": "APPROVED", "submittedAt": "2026-02-03T10:00:00+00:00", "author": {"login": "reviewer"}}]},
                }
            ],
        }
        return fixtures.get((repo, window.label), [])


class PartialAccessGitHubClient(FakeGitHubClient):
    def validate_repo(self, owner: str, repo: str) -> tuple[bool, str, str]:
        if repo == "missing":
            return False, repo, "404 Not Found"
        return True, repo.lower(), ""


def _load_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("GITHUB_METRIC_OWNER_OR_ORGANIZATION", None)
    env.pop("GITHUB_METRIC_REPO", None)
    env.pop("GITHUB_REPO_FOR_PR_TRACKING", None)
    return env


def test_show_config_script_runs_as_cli(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    out_dir = tmp_path / "show-config-run"
    env_file.write_text(
        "\n".join(
            [
                "GITHUB_METRIC_OWNER_OR_ORGANIZATION=example-org",
                "GITHUB_METRIC_REPO=api,web",
                "GITHUB_REPO_FOR_PR_TRACKING=",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/engineering_throughput_show_config.py",
            "--env-file",
            str(env_file),
            "--team-config",
            str(FIXTURE_DIR / "team-config.json"),
            "--jira-csv-dir",
            str(FIXTURE_DIR),
            "--baseline-year",
            "2025",
            "--focus-year",
            "2026",
            "--focus-start",
            "2026-02-01",
                "--date-end",
                "2026-03-31",
                "--out-dir",
                str(out_dir),
            ],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        env=_subprocess_env(),
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Owner: example-org" in result.stdout
    assert "Repos (2): api, web" in result.stdout
    assert "Spreadsheet mode: create" in result.stdout


def test_build_script_show_config_mode_runs_as_cli(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    out_dir = tmp_path / "build-show-config-run"
    env_file.write_text(
        "\n".join(
            [
                "GITHUB_METRIC_OWNER_OR_ORGANIZATION=example-org",
                "GITHUB_METRIC_REPO=api,web",
                "GITHUB_REPO_FOR_PR_TRACKING=",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/engineering_throughput_build.py",
            "--env-file",
            str(env_file),
            "--team-config",
            str(FIXTURE_DIR / "team-config.json"),
            "--jira-csv-dir",
            str(FIXTURE_DIR),
            "--baseline-year",
            "2025",
            "--focus-year",
            "2026",
            "--focus-start",
            "2026-02-01",
                "--date-end",
                "2026-03-31",
                "--out-dir",
                str(out_dir),
                "--show-config",
            ],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        env=_subprocess_env(),
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Focus: 2026 Feb-Mar" in result.stdout
    assert "Spreadsheet mode: create" in result.stdout


def test_build_script_writes_run_config_summaries_and_combined_payload(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "GITHUB_METRIC_OWNER_OR_ORGANIZATION=example-org",
                "GITHUB_METRIC_REPO=api,web",
                "GITHUB_REPO_FOR_PR_TRACKING=",
            ]
        ),
        encoding="utf-8",
    )
    module = _load_module(Path("scripts/engineering_throughput_build.py"), "engineering_throughput_build")
    out_dir = tmp_path / "run"

    exit_code = module.main(
        [
            "--env-file",
            str(env_file),
            "--team-config",
            str(FIXTURE_DIR / "team-config.json"),
            "--jira-csv-dir",
            str(FIXTURE_DIR),
            "--baseline-year",
            "2025",
            "--focus-year",
            "2026",
            "--focus-start",
            "2026-02-01",
            "--date-end",
            "2026-03-31",
            "--out-dir",
            str(out_dir),
        ],
        github_client=FakeGitHubClient(),
    )

    assert exit_code == 0
    assert (out_dir / "run_config.json").exists()
    assert (out_dir / "github_metrics_payload.json").exists()
    assert (out_dir / "github_summary.json").exists()
    assert (out_dir / "jira_summary.json").exists()
    assert (out_dir / "sheet_payload.json").exists()

    payload = json.loads((out_dir / "sheet_payload.json").read_text(encoding="utf-8"))
    tabs = payload["tabs"]
    assert "Jira Summary" in tabs
    assert "GitHub Summary" in tabs
    assert "Recommendations" in tabs
    jira_summary = next(item for item in payload["data"] if item["tab"] == "Jira Summary")
    assert any(row[:3] == ["2025-03", 0, 0] for row in jira_summary["values"])
    assert any(row[:3] == ["2026-01", 0, 0] for row in jira_summary["values"])

    run_config = json.loads((out_dir / "run_config.json").read_text(encoding="utf-8"))
    assert run_config["jira_source"]["mode"] == "team_config"
    assert run_config["spreadsheet_mode"] == "create"


def test_build_script_fails_when_requested_repo_access_is_incomplete(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "GITHUB_METRIC_OWNER_OR_ORGANIZATION=example-org",
                "GITHUB_METRIC_REPO=api,missing",
                "GITHUB_REPO_FOR_PR_TRACKING=",
            ]
        ),
        encoding="utf-8",
    )
    module = _load_module(Path("scripts/engineering_throughput_build.py"), "engineering_throughput_build_partial")
    out_dir = tmp_path / "run"

    with pytest.raises(ValueError, match="Inaccessible repos; update repo config or access before building: missing \\(404 Not Found\\)"):
        module.main(
            [
                "--env-file",
                str(env_file),
                "--team-config",
                str(FIXTURE_DIR / "team-config.json"),
                "--jira-csv-dir",
                str(FIXTURE_DIR),
                "--baseline-year",
                "2025",
                "--focus-year",
                "2026",
                "--focus-start",
                "2026-02-01",
                "--date-end",
                "2026-03-31",
                "--out-dir",
                str(out_dir),
            ],
            github_client=PartialAccessGitHubClient(),
        )

    assert not (out_dir / "sheet_payload.json").exists()
