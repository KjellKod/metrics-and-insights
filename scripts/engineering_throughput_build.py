#!/usr/bin/env python3
"""Build committed engineering throughput artifacts from Jira CSV + GitHub data."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engineering_throughput.config import build_argument_parser, print_run_config, resolve_run_config
from engineering_throughput.github_payload import build_github_sections
from engineering_throughput.jira_payload import build_jira_sections
from engineering_throughput.recommendation_signals import (
    build_recommendation_signals,
    load_agent_recommendations_section,
)
from engineering_throughput.sheet_builder import assemble_sheet_payload
from git_metrics.throughput_collect import GitHubClient, collect_merged_pr_rows, github_token
from git_metrics.throughput_summary import summarize_github_rows
from jira_metrics.throughput_summary import parse_individual_csv, summarize_jira_artifacts


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _load_jira_artifacts(config) -> list:
    artifacts = []
    if config.teams:
        for team in config.teams:
            artifacts.append(parse_individual_csv(team.jira_csv, team_name=team.name))
        return artifacts
    for path in config.jira_source.artifacts:
        artifacts.append(parse_individual_csv(path))
    return artifacts


def _raise_for_inaccessible_repos(collection) -> None:
    if not collection.inaccessible_repos:
        return
    details = ", ".join(
        f"{issue.repo} ({issue.reason})" if issue.reason else issue.repo for issue in collection.inaccessible_repos
    )
    raise ValueError(f"Inaccessible repos; update repo config or access before building: {details}")


def main(argv: list[str] | None = None, github_client: GitHubClient | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    config = resolve_run_config(args)
    if config.show_config:
        return print_run_config(config)

    client = github_client or GitHubClient(github_token(config))
    collection = collect_merged_pr_rows(config, client)
    _raise_for_inaccessible_repos(collection)
    github_summary = summarize_github_rows(list(collection.detail_rows), config)
    jira_summary = summarize_jira_artifacts(_load_jira_artifacts(config), config.date_window)
    recommendation_signals = build_recommendation_signals(
        jira_summary,
        github_summary,
        config.teams,
        config.date_window,
    )

    base_sections = []
    base_sections.extend(build_jira_sections(jira_summary, config.teams, config.date_window))
    base_sections.extend(build_github_sections(github_summary, config.date_window))
    base_payload = assemble_sheet_payload(
        base_sections,
        metadata={
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "owner": config.owner,
            "repos": list(collection.repos),
            "requested_repos": list(collection.requested_repos),
            "inaccessible_repos": [issue.to_dict() for issue in collection.inaccessible_repos],
            "date_window": config.date_window.to_dict(),
            "spreadsheet_mode": config.spreadsheet_mode,
            "spreadsheet_id": config.spreadsheet_id,
            "recommendations_required": True,
        },
    )

    config.output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(config.output_dir / "github_metrics_payload.json", collection.to_dict())
    _write_json(config.output_dir / "github_summary.json", github_summary.to_dict())
    _write_json(config.output_dir / "jira_summary.json", jira_summary.to_dict())
    _write_json(config.output_dir / "recommendation_signals.json", recommendation_signals.to_dict())
    _write_json(config.output_dir / "base_sheet_payload.json", base_payload.to_dict())

    if config.recommendations_file is None:
        raise ValueError(
            "Agent-authored recommendations are required to produce sheet_payload.json. "
            f"Base artifacts were written to {config.output_dir}, including recommendation_signals.json "
            "and base_sheet_payload.json. Run this from an agent workflow or rerun with "
            "--recommendations-file pointing at an agent-authored Recommendations section JSON. "
            "Human-only local runs without agent access stop after local artifact generation."
        )

    recommendations_section = load_agent_recommendations_section(config.recommendations_file)
    payload = assemble_sheet_payload(
        [*base_sections, recommendations_section],
        metadata=base_payload.metadata,
    )
    _write_json(config.output_dir / "sheet_payload.json", payload.to_dict())
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
