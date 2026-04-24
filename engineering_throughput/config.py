"""Runtime config resolution for engineering throughput scripts."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from engineering_throughput.date_ranges import resolve_date_window
from engineering_throughput.models import (
    ExcludeConfig,
    ExcludeRule,
    ExcludeWindow,
    JiraSource,
    RunConfig,
    TeamConfig,
)


ENV_OWNER_KEY = "GITHUB_METRIC_OWNER_OR_ORGANIZATION"
ENV_REPO_KEYS = ("GITHUB_METRIC_REPO", "GITHUB_REPO_FOR_PR_TRACKING")
FIXED_SHEET_TITLES = (
    "Jira Summary",
    "GitHub Summary",
    "GitHub No Approval",
    "GitHub Repos",
    "GitHub Authors",
    "GitHub Flags",
    "Recommendations",
)


def read_env_file(path: Path) -> dict[str, str]:
    """Read simple KEY=VALUE pairs from an env file."""

    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def parse_repo_list(raw: str | None) -> list[str]:
    """Split a comma-separated repo list and drop blanks."""

    if not raw:
        return []
    values: list[str] = []
    for part in raw.split(","):
        repo = part.strip().strip("'\"")
        if repo:
            values.append(repo)
    return values


def unique_preserving_order(values: Iterable[str]) -> list[str]:
    """Deduplicate case-insensitively while preserving the first spelling."""

    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        lowered = value.lower()
        if lowered not in seen:
            seen.add(lowered)
            result.append(value)
    return result


def parse_iso_date(value: str | None) -> date | None:
    """Parse an optional YYYY-MM-DD date string."""

    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid ISO date: {value}") from exc


def _load_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Missing config file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc.msg}") from exc


def _normalize_string_list(value: Any, *, field_path: str, split_commas: bool = False) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"{field_path} must be a list")

    normalized: list[str] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, str):
            raise ValueError(f"{field_path}[{index}] must be a string")
        if split_commas:
            normalized.extend(parse_repo_list(item))
            continue
        entry = item.strip()
        if entry:
            normalized.append(entry)
    return tuple(unique_preserving_order(normalized))


def _validate_team_name(name: str, *, index: int, seen_names: dict[str, str]) -> None:
    reserved_titles = {title.lower(): title for title in FIXED_SHEET_TITLES}
    normalized_name = name.lower()
    reserved_title = reserved_titles.get(normalized_name)
    if reserved_title is not None:
        raise ValueError(f"teams[{index}].name conflicts with reserved tab title '{reserved_title}'")
    if normalized_name in seen_names:
        raise ValueError(f"teams[{index}].name duplicates team '{seen_names[normalized_name]}'")
    seen_names[normalized_name] = name


def load_team_config(team_config_path: Path | None, jira_csv_dir: Path | None) -> tuple[tuple[TeamConfig, ...], JiraSource]:
    """Load runtime team metadata.

    First-pass schema:
    {
      "teams": [
        {
          "name": "Platform",
          "jira_csv": "platform_individual_metrics.csv",
          "repos": ["api", "worker"]
        }
      ]
    }

    Rules:
    - `teams` is required when a team config file is provided.
    - Each team entry requires `name` and `jira_csv`.
    - `repos` is optional and only used for team-scoped GitHub context.
    - Relative `jira_csv` paths resolve against `--jira-csv-dir` when provided,
      otherwise against the team config file's parent directory.
    - When the file is omitted, the build falls back to global Jira scope only:
      `--jira-csv-dir` must point at one or more `*_individual_metrics.csv`
      files and no team tabs will be generated.
    """

    if team_config_path is None:
        if jira_csv_dir is None:
            raise ValueError("Jira input is required; set --jira-csv-dir or --team-config")
        if not jira_csv_dir.exists() or not jira_csv_dir.is_dir():
            raise ValueError(f"Jira CSV directory not found: {jira_csv_dir}")
        artifacts = tuple(sorted(jira_csv_dir.glob("*_individual_metrics.csv")))
        if not artifacts:
            raise ValueError(f"No Jira CSV artifacts found in {jira_csv_dir}")
        return (), JiraSource(mode="directory", directory=jira_csv_dir, artifacts=artifacts)

    payload = _load_json_file(team_config_path)
    teams_payload = payload.get("teams") if isinstance(payload, dict) else None
    if not isinstance(teams_payload, list) or not teams_payload:
        raise ValueError(f"{team_config_path} must contain a non-empty 'teams' list")

    base_dir = jira_csv_dir or team_config_path.parent
    teams: list[TeamConfig] = []
    seen_team_names: dict[str, str] = {}
    for index, item in enumerate(teams_payload, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"teams[{index}] must be an object")
        name = str(item.get("name", "")).strip()
        jira_csv_value = str(item.get("jira_csv", "")).strip()
        if not name or not jira_csv_value:
            raise ValueError(f"teams[{index}] must define non-empty 'name' and 'jira_csv'")
        _validate_team_name(name, index=index, seen_names=seen_team_names)
        jira_csv_path = Path(jira_csv_value)
        if not jira_csv_path.is_absolute():
            jira_csv_path = base_dir / jira_csv_path
        repos = _normalize_string_list(item.get("repos"), field_path=f"teams[{index}].repos", split_commas=True)
        if not jira_csv_path.exists():
            raise ValueError(f"Jira CSV not found for team '{name}': {jira_csv_path}")
        teams.append(TeamConfig(name=name, jira_csv=jira_csv_path, repos=repos))

    return tuple(teams), JiraSource(
        mode="team_config",
        directory=jira_csv_dir,
        artifacts=tuple(team.jira_csv for team in teams),
    )


def load_exclude_config(path: Path | None) -> ExcludeConfig:
    """Load the optional process-eligibility exclusion config.

    First-pass schema:
    {
      "windows": [
        {"name": "hackathon", "start": "2026-02-10", "end": "2026-02-12"}
      ],
      "rules": [
        {
          "reason": "release-promotion",
          "repos": ["mobile"],
          "authors": ["release-bot"],
          "title_contains": ["release"]
        }
      ]
    }

    Rules:
    - `windows` and `rules` are both optional.
    - Window matches exclude any PR whose merged date falls inside the window.
    - Rule matches can filter by repo, author, title substring, and optional
      start/end dates.
    - When the file is omitted, process metrics use all collected PR rows.
    """

    if path is None:
        return ExcludeConfig()

    payload = _load_json_file(path)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must be a JSON object")

    windows_payload = payload.get("windows", [])
    if not isinstance(windows_payload, list):
        raise ValueError(f"{path} field 'windows' must be a list")

    windows: list[ExcludeWindow] = []
    for index, item in enumerate(windows_payload, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"windows[{index}] must be an object")
        name = str(item.get("name", "")).strip()
        start = parse_iso_date(item.get("start"))
        end = parse_iso_date(item.get("end"))
        if not name or start is None or end is None:
            raise ValueError(f"windows[{index}] must define name/start/end")
        if start > end:
            raise ValueError(f"windows[{index}] start must be on or before end")
        windows.append(ExcludeWindow(name=name, start=start, end=end))

    rules_payload = payload.get("rules", [])
    if not isinstance(rules_payload, list):
        raise ValueError(f"{path} field 'rules' must be a list")

    rules: list[ExcludeRule] = []
    for index, item in enumerate(rules_payload, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"rules[{index}] must be an object")
        reason = str(item.get("reason", "")).strip()
        if not reason:
            raise ValueError(f"rules[{index}] must define a non-empty reason")
        repos = _normalize_string_list(item.get("repos"), field_path=f"rules[{index}].repos")
        authors = _normalize_string_list(item.get("authors"), field_path=f"rules[{index}].authors")
        title_contains = tuple(
            value.lower()
            for value in _normalize_string_list(item.get("title_contains"), field_path=f"rules[{index}].title_contains")
        )
        start = parse_iso_date(item.get("start"))
        end = parse_iso_date(item.get("end"))
        if not any((repos, authors, title_contains, start, end)):
            raise ValueError(f"rules[{index}] must define at least one matcher")
        if start is not None and end is not None and start > end:
            raise ValueError(f"rules[{index}] start must be on or before end")
        rules.append(
            ExcludeRule(
                reason=reason,
                repos=repos,
                authors=authors,
                title_contains=title_contains,
                start=start,
                end=end,
            )
        )

    return ExcludeConfig(windows=tuple(windows), rules=tuple(rules))


def write_run_config(config: RunConfig) -> Path:
    """Persist the resolved runtime contract to the run directory."""

    config.output_dir.mkdir(parents=True, exist_ok=True)
    path = config.output_dir / "run_config.json"
    path.write_text(json.dumps(config.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return path


def print_run_config(config: RunConfig) -> int:
    """Print a deterministic summary for repo-confirmation workflows."""

    date_window = config.date_window
    teams_display = ", ".join(team.name for team in config.teams) if config.teams else "global-only"
    artifact_display = ", ".join(str(path) for path in config.jira_source.artifacts)
    print(f"Owner: {config.owner}")
    print(f"Repo source: {config.repo_source}")
    print(f"Repos ({len(config.repos)}): {', '.join(config.repos)}")
    print(f"Baseline: {date_window.baseline_label}")
    print(f"Focus: {date_window.focus_label}")
    print(f"Comparison: {date_window.comparison_label}")
    print(f"Date window: {date_window.start.isoformat()} to {date_window.end.isoformat()}")
    print(f"Focus start: {date_window.focus_start.isoformat()}")
    print(f"Jira source mode: {config.jira_source.mode}")
    print(f"Jira source directory: {config.jira_source.directory or 'n/a'}")
    print(f"Jira artifacts: {artifact_display}")
    print(f"Teams: {teams_display}")
    print(f"Team config source: {config.team_config_path or 'n/a'}")
    print(f"Exclude config source: {config.exclude_config_path or 'n/a'}")
    print(f"Spreadsheet mode: {config.spreadsheet_mode}")
    print(f"Spreadsheet ID: {config.spreadsheet_id or 'n/a'}")
    print(f"Output dir: {config.output_dir}")
    return 0


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the shared CLI parser used by both committed entrypoints."""

    parser = argparse.ArgumentParser(description="Build engineering throughput artifacts.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--owner")
    parser.add_argument("--repos", help="Comma-separated repo list")
    parser.add_argument("--baseline-year", type=int)
    parser.add_argument("--focus-year", type=int)
    parser.add_argument("--focus-start")
    parser.add_argument("--date-end")
    parser.add_argument("--team-config")
    parser.add_argument("--jira-csv-dir")
    parser.add_argument("--spreadsheet-mode", choices=("create", "update"), default="create")
    parser.add_argument("--spreadsheet-id")
    parser.add_argument("--out-dir")
    parser.add_argument("--exclude-config")
    parser.add_argument("--show-config", action="store_true")
    return parser


def resolve_run_config(args: argparse.Namespace, current_date: date | None = None) -> RunConfig:
    """Resolve CLI + env inputs into the runtime contract.

    Precedence:
    - CLI
    - env file
    - process env
    - built-in defaults
    """

    today = current_date or date.today()
    env_file = Path(args.env_file)
    env_values = read_env_file(env_file)

    if args.owner is not None:
        owner = args.owner.strip()
        if not owner:
            raise ValueError("--owner cannot be blank")
    else:
        owner = env_values.get(ENV_OWNER_KEY) or os.environ.get(ENV_OWNER_KEY)
    if not owner:
        raise ValueError(f"Missing owner; set --owner or {ENV_OWNER_KEY}")

    if args.repos is not None:
        requested_repos = unique_preserving_order(parse_repo_list(args.repos))
        repo_source = "cli"
        if not requested_repos:
            raise ValueError("--repos cannot be blank")
    else:
        requested_repos = []
        for key in ENV_REPO_KEYS:
            requested_repos.extend(parse_repo_list(env_values.get(key) or os.environ.get(key)))
        requested_repos = unique_preserving_order(requested_repos)
        repo_source = "env"
    if not requested_repos:
        keys = ", ".join(ENV_REPO_KEYS)
        raise ValueError(f"Missing repos; set --repos or one of {keys}")

    date_window = resolve_date_window(
        baseline_year=args.baseline_year,
        focus_year=args.focus_year,
        focus_start=parse_iso_date(args.focus_start),
        date_end=parse_iso_date(args.date_end),
        today=today,
    )

    if args.spreadsheet_mode == "update" and not args.spreadsheet_id:
        raise ValueError("--spreadsheet-id is required when --spreadsheet-mode=update")
    if args.spreadsheet_mode == "create" and args.spreadsheet_id:
        raise ValueError("--spreadsheet-id is not allowed when --spreadsheet-mode=create")

    output_dir = Path(args.out_dir) if args.out_dir else Path(".ws") / f"engineering-throughput-{today.isoformat()}"
    team_config_path = Path(args.team_config) if args.team_config else None
    jira_csv_dir = Path(args.jira_csv_dir) if args.jira_csv_dir else None
    exclude_config_path = Path(args.exclude_config) if args.exclude_config else None

    teams, jira_source = load_team_config(team_config_path, jira_csv_dir)
    exclude_config = load_exclude_config(exclude_config_path)

    config = RunConfig(
        owner=owner,
        requested_repos=tuple(requested_repos),
        repos=tuple(requested_repos),
        repo_source=repo_source,
        env_file=env_file,
        output_dir=output_dir,
        date_window=date_window,
        jira_source=jira_source,
        teams=teams,
        team_config_path=team_config_path,
        exclude_config_path=exclude_config_path,
        exclude_config=exclude_config,
        spreadsheet_mode=args.spreadsheet_mode,
        spreadsheet_id=args.spreadsheet_id,
        show_config=bool(args.show_config),
    )
    write_run_config(config)
    return config
