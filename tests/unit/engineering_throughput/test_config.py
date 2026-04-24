from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from engineering_throughput.config import (
    build_argument_parser,
    load_exclude_config,
    load_team_config,
    print_run_config,
    resolve_run_config,
)


FIXTURE_DIR = Path("tests/fixtures/engineering_throughput")


@pytest.fixture(autouse=True)
def _clear_metric_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "GITHUB_METRIC_OWNER_OR_ORGANIZATION",
        "GITHUB_METRIC_REPO",
        "GITHUB_REPO_FOR_PR_TRACKING",
    ):
        monkeypatch.delenv(key, raising=False)


def _write_env(path: Path, repos: str = "api,web") -> None:
    path.write_text(
        "\n".join(
            [
                "GITHUB_METRIC_OWNER_OR_ORGANIZATION=example-org",
                f"GITHUB_METRIC_REPO={repos}",
                "GITHUB_REPO_FOR_PR_TRACKING=",
            ]
        ),
        encoding="utf-8",
    )


def test_resolve_run_config_defaults_to_previous_and_current_year(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    _write_env(env_file)
    args = build_argument_parser().parse_args(
        [
            "--env-file",
            str(env_file),
            "--team-config",
            str(FIXTURE_DIR / "team-config.json"),
            "--jira-csv-dir",
            str(FIXTURE_DIR),
            "--out-dir",
            str(tmp_path / "run"),
        ]
    )

    config = resolve_run_config(args, current_date=date(2026, 4, 23))

    assert config.date_window.baseline_year == 2025
    assert config.date_window.focus_year == 2026
    assert config.date_window.focus_label == "2026 YTD"
    assert config.teams[0].name == "Alpha Team"
    run_config = json.loads((tmp_path / "run" / "run_config.json").read_text(encoding="utf-8"))
    assert run_config["jira_source"]["mode"] == "team_config"


def test_resolve_run_config_reads_repos_from_cli_or_env_without_silent_fallback(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    _write_env(env_file, repos="env-repo")

    cli_args = build_argument_parser().parse_args(
        [
            "--env-file",
            str(env_file),
            "--team-config",
            str(FIXTURE_DIR / "team-config.json"),
            "--jira-csv-dir",
            str(FIXTURE_DIR),
            "--repos",
            "cli-a,cli-b",
            "--out-dir",
            str(tmp_path / "cli-run"),
        ]
    )
    cli_config = resolve_run_config(cli_args, current_date=date(2026, 4, 23))
    assert cli_config.repos == ("cli-a", "cli-b")
    assert cli_config.repo_source == "cli"

    env_args = build_argument_parser().parse_args(
        [
            "--env-file",
            str(env_file),
            "--jira-csv-dir",
            str(FIXTURE_DIR),
            "--out-dir",
            str(tmp_path / "env-run"),
        ]
    )
    env_config = resolve_run_config(env_args, current_date=date(2026, 4, 23))
    assert env_config.repos == ("env-repo",)
    assert env_config.repo_source == "env"


def test_resolve_run_config_raises_when_repo_resolution_is_empty(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("GITHUB_METRIC_OWNER_OR_ORGANIZATION=example-org\n", encoding="utf-8")
    args = build_argument_parser().parse_args(
        [
            "--env-file",
            str(env_file),
            "--jira-csv-dir",
            str(FIXTURE_DIR),
            "--out-dir",
            str(tmp_path / "run"),
        ]
    )

    with pytest.raises(ValueError, match="Missing repos"):
        resolve_run_config(args, current_date=date(2026, 4, 23))


def test_resolve_run_config_validates_spreadsheet_mode_and_id(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    _write_env(env_file)

    update_args = build_argument_parser().parse_args(
        [
            "--env-file",
            str(env_file),
            "--jira-csv-dir",
            str(FIXTURE_DIR),
            "--spreadsheet-mode",
            "update",
            "--out-dir",
            str(tmp_path / "update-run"),
        ]
    )
    with pytest.raises(ValueError, match="--spreadsheet-id is required"):
        resolve_run_config(update_args, current_date=date(2026, 4, 23))

    create_args = build_argument_parser().parse_args(
        [
            "--env-file",
            str(env_file),
            "--jira-csv-dir",
            str(FIXTURE_DIR),
            "--spreadsheet-mode",
            "create",
            "--spreadsheet-id",
            "abc123",
            "--out-dir",
            str(tmp_path / "create-run"),
        ]
    )
    with pytest.raises(ValueError, match="--spreadsheet-id is not allowed"):
        resolve_run_config(create_args, current_date=date(2026, 4, 23))


def test_resolve_run_config_rejects_non_month_aligned_focus_window(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    _write_env(env_file)

    args = build_argument_parser().parse_args(
        [
            "--env-file",
            str(env_file),
            "--jira-csv-dir",
            str(FIXTURE_DIR),
            "--focus-start",
            "2026-02-15",
            "--date-end",
            "2026-03-15",
            "--out-dir",
            str(tmp_path / "run"),
        ]
    )

    with pytest.raises(ValueError, match="--focus-start must be the first day of a month"):
        resolve_run_config(args, current_date=date(2026, 4, 23))


def test_resolve_run_config_rejects_blank_cli_owner_or_repos(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    _write_env(env_file, repos="env-repo")

    blank_owner_args = build_argument_parser().parse_args(
        [
            "--env-file",
            str(env_file),
            "--jira-csv-dir",
            str(FIXTURE_DIR),
            "--owner",
            "",
            "--out-dir",
            str(tmp_path / "blank-owner"),
        ]
    )
    with pytest.raises(ValueError, match="--owner cannot be blank"):
        resolve_run_config(blank_owner_args, current_date=date(2026, 4, 23))

    blank_repos_args = build_argument_parser().parse_args(
        [
            "--env-file",
            str(env_file),
            "--jira-csv-dir",
            str(FIXTURE_DIR),
            "--repos",
            "",
            "--out-dir",
            str(tmp_path / "blank-repos"),
        ]
    )
    with pytest.raises(ValueError, match="--repos cannot be blank"):
        resolve_run_config(blank_repos_args, current_date=date(2026, 4, 23))


def test_show_config_output_lists_owner_repos_focus_window_and_sources(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    env_file = tmp_path / ".env"
    _write_env(env_file)
    args = build_argument_parser().parse_args(
        [
            "--env-file",
            str(env_file),
            "--team-config",
            str(FIXTURE_DIR / "team-config.json"),
            "--jira-csv-dir",
            str(FIXTURE_DIR),
            "--focus-start",
            "2026-02-01",
            "--date-end",
            "2026-04-23",
            "--exclude-config",
            str(FIXTURE_DIR / "exclude-config.json"),
            "--out-dir",
            str(tmp_path / "run"),
        ]
    )

    config = resolve_run_config(args, current_date=date(2026, 4, 23))
    assert print_run_config(config) == 0
    output = capsys.readouterr().out
    assert "Owner: example-org" in output
    assert "Repos (2): api, web" in output
    assert "Focus: 2026 Feb-Apr" in output
    assert f"Jira source directory: {FIXTURE_DIR}" in output
    assert f"Exclude config source: {FIXTURE_DIR / 'exclude-config.json'}" in output


def test_load_team_config_rejects_missing_or_empty_teams_list(tmp_path: Path) -> None:
    missing_teams = tmp_path / "missing-teams.json"
    missing_teams.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="non-empty 'teams' list"):
        load_team_config(missing_teams, FIXTURE_DIR)

    empty_teams = tmp_path / "empty-teams.json"
    empty_teams.write_text('{"teams": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="non-empty 'teams' list"):
        load_team_config(empty_teams, FIXTURE_DIR)


def test_load_team_config_rejects_missing_name_or_missing_csv() -> None:
    with pytest.raises(ValueError, match="teams\\[1\\] must define non-empty 'name' and 'jira_csv'"):
        load_team_config(FIXTURE_DIR / "team-missing-name.json", FIXTURE_DIR)

    with pytest.raises(ValueError, match="Jira CSV not found"):
        load_team_config(FIXTURE_DIR / "team-missing-csv.json", FIXTURE_DIR)


def test_load_team_config_rejects_non_list_repos() -> None:
    with pytest.raises(ValueError, match=r"teams\[1\]\.repos must be a list"):
        load_team_config(FIXTURE_DIR / "team-invalid-repos.json", FIXTURE_DIR)


def test_load_team_config_rejects_duplicate_or_reserved_team_names(tmp_path: Path) -> None:
    duplicate_names = tmp_path / "duplicate-names.json"
    duplicate_names.write_text(
        json.dumps(
            {
                "teams": [
                    {"name": "Platform", "jira_csv": "alpha_individual_metrics.csv"},
                    {"name": "Platform", "jira_csv": "beta_individual_metrics.csv"},
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicates team"):
        load_team_config(duplicate_names, FIXTURE_DIR)

    reserved_name = tmp_path / "reserved-name.json"
    reserved_name.write_text(
        json.dumps({"teams": [{"name": "Jira Summary", "jira_csv": "alpha_individual_metrics.csv"}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="conflicts with reserved tab title"):
        load_team_config(reserved_name, FIXTURE_DIR)


def test_load_exclude_config_rejects_missing_window_dates_and_non_dict_rules(tmp_path: Path) -> None:
    missing_date = tmp_path / "exclude-missing-date.json"
    missing_date.write_text('{"windows":[{"name":"hackathon","start":"2026-02-10"}]}', encoding="utf-8")
    with pytest.raises(ValueError, match=r"windows\[1\] must define name/start/end"):
        load_exclude_config(missing_date)

    non_dict_rule = tmp_path / "exclude-non-dict-rule.json"
    non_dict_rule.write_text('{"rules":["release"]}', encoding="utf-8")
    with pytest.raises(ValueError, match=r"rules\[1\] must be an object"):
        load_exclude_config(non_dict_rule)


def test_load_exclude_config_rejects_non_list_rule_fields(tmp_path: Path) -> None:
    invalid_rule_fields = tmp_path / "exclude-invalid-rule-fields.json"
    invalid_rule_fields.write_text(
        '{"rules":[{"reason":"release","repos":"mobile","authors":["bot"],"title_contains":["release"]}]}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"rules\[1\]\.repos must be a list"):
        load_exclude_config(invalid_rule_fields)


def test_load_exclude_config_rejects_reason_only_rule(tmp_path: Path) -> None:
    reason_only_rule = tmp_path / "exclude-reason-only-rule.json"
    reason_only_rule.write_text('{"rules":[{"reason":"oops"}]}', encoding="utf-8")
    with pytest.raises(ValueError, match=r"rules\[1\] must define at least one matcher"):
        load_exclude_config(reason_only_rule)


def test_load_exclude_config_rejects_inverted_date_ranges(tmp_path: Path) -> None:
    inverted_window = tmp_path / "exclude-inverted-window.json"
    inverted_window.write_text(
        '{"windows":[{"name":"hackathon","start":"2026-02-10","end":"2026-02-09"}]}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"windows\[1\] start must be on or before end"):
        load_exclude_config(inverted_window)

    inverted_rule = tmp_path / "exclude-inverted-rule.json"
    inverted_rule.write_text(
        '{"rules":[{"reason":"release","start":"2026-05-01","end":"2026-01-01"}]}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"rules\[1\] start must be on or before end"):
        load_exclude_config(inverted_rule)
