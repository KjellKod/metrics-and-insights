#!/usr/bin/env python3
"""Report CI maturity across repositories owned by a GitHub user or organization."""

from __future__ import annotations

import argparse
import base64
import csv
import fnmatch
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import requests
from dotenv import load_dotenv

load_dotenv()

GITHUB_REST_URL = "https://api.github.com"
DEFAULT_TOKEN_ENV = "GITHUB_TOKEN_READONLY_WEB"
DEFAULT_CACHE_FILE = ".ci_maturity_cache.json"

LINTER_PATTERNS = (
    "lint",
    "eslint",
    "ruff",
    "flake8",
    "pylint",
    "black --check",
    "prettier --check",
    "golangci-lint",
    "shellcheck",
    "hadolint",
)
UNIT_TEST_PATTERNS = (
    "unit",
    "pytest",
    "unittest",
    "jest",
    "vitest",
    "npm test",
    "yarn test",
    "pnpm test",
    "go test",
    "cargo test",
    "dotnet test",
    "mvn test",
    "gradle test",
)
INTEGRATION_PATTERNS = (
    "smoke",
    "integration",
    "e2e",
    "end-to-end",
    "playwright",
    "cypress",
    "selenium",
    "postman",
)
AGENTIC_PATTERNS = (
    "agentic",
    "ai review",
    "ai code review",
    "llm review",
    "automated code review",
    "review agent",
    "agent review",
    "code review agent",
)

AGENTIC_PATTERNS_ENV = "CI_MATURITY_AGENTIC_PATTERNS"


@dataclass
class RepoFilterResult:
    included: list[dict[str, Any]]
    skipped: list[dict[str, str]]


@dataclass
class GitHubRateLimitEvent:
    url: str
    status_code: int
    slept_seconds: float
    reset_at: str | None = None
    reason: str = "rate_limit"


@dataclass
class GitHubClient:
    token: str
    sleep_fn: Any = time.sleep
    now_fn: Any = lambda: datetime.now(timezone.utc)
    max_retries: int = 4
    session: requests.Session = field(init=False)
    rate_limit_events: list[GitHubRateLimitEvent] = field(default_factory=list)
    auth_source: str = "unknown"

    def __post_init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"token {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    def get(self, path_or_url: str, *, params: dict[str, Any] | None = None) -> requests.Response:
        url = path_or_url if path_or_url.startswith("https://") else f"{GITHUB_REST_URL}{path_or_url}"
        for attempt in range(1, self.max_retries + 1):
            response = self.session.get(url, params=params, timeout=60)
            if not self._should_wait_for_rate_limit(response) or attempt == self.max_retries:
                if response.status_code == 401:
                    raise RuntimeError(
                        f"GitHub rejected token from {self.auth_source} with 401 Unauthorized. "
                        "Refresh that token or confirm it is valid for api.github.com."
                    )
                response.raise_for_status()
                return response
            self._wait_for_rate_limit(response, url)
        raise RuntimeError(f"GitHub request failed after {self.max_retries} attempts: {url}")

    def get_json(self, path_or_url: str, *, params: dict[str, Any] | None = None) -> Any:
        return self.get(path_or_url, params=params).json()

    def paginated_get(self, path: str, *, params: dict[str, Any] | None = None) -> Iterable[Any]:
        url: str | None = f"{GITHUB_REST_URL}{path}"
        request_params = dict(params or {})
        request_params.setdefault("per_page", 100)
        while url:
            response = self.get(url, params=request_params)
            payload = response.json()
            if isinstance(payload, list):
                yield from payload
            else:
                raise RuntimeError(f"Expected list response from GitHub pagination endpoint: {url}")
            url = response.links.get("next", {}).get("url")
            request_params = None

    def owner_type(self, owner: str) -> str:
        payload = self.get_json(f"/users/{owner}")
        return str(payload.get("type") or "").lower()

    def list_repositories(self, owner: str) -> list[dict[str, Any]]:
        owner_type = self.owner_type(owner)
        if owner_type == "organization":
            path = f"/orgs/{owner}/repos"
            params = {"type": "all", "sort": "full_name", "direction": "asc"}
        else:
            path = f"/users/{owner}/repos"
            params = {"type": "owner", "sort": "full_name", "direction": "asc"}
        return list(self.paginated_get(path, params=params))

    def workflow_files(self, owner: str, repo: str, default_branch: str | None) -> list[dict[str, str]]:
        params = {"ref": default_branch} if default_branch else None
        try:
            contents = self.get_json(f"/repos/{owner}/{repo}/contents/.github/workflows", params=params)
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code in {403, 404}:
                return []
            raise
        if not isinstance(contents, list):
            return []

        workflows = []
        for item in contents:
            name = item.get("name") or ""
            if not name.endswith((".yml", ".yaml")):
                continue
            try:
                workflow_payload = self.get_json(item["url"])
            except requests.HTTPError as exc:
                if exc.response is not None and exc.response.status_code in {403, 404}:
                    continue
                raise
            encoded = workflow_payload.get("content") or ""
            encoding = workflow_payload.get("encoding")
            if encoding != "base64" or not encoded:
                continue
            text = base64.b64decode(encoded).decode("utf-8", errors="replace")
            workflows.append({"path": item.get("path") or f".github/workflows/{name}", "text": text})
        return workflows

    def latest_workflow_run(self, owner: str, repo: str) -> dict[str, Any] | None:
        try:
            payload = self.get_json(f"/repos/{owner}/{repo}/actions/runs", params={"per_page": 1})
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code in {403, 404}:
                return {"_status": "unknown", "reason": f"{exc.response.status_code} {exc.response.reason}"}
            raise
        runs = payload.get("workflow_runs") or []
        return runs[0] if runs else None

    def _should_wait_for_rate_limit(self, response: requests.Response) -> bool:
        if response.status_code == 429:
            return True
        if response.status_code != 403:
            return False
        text = response.text.lower()
        return any(term in text for term in ("rate limit", "secondary rate limit", "api rate limit exceeded", "abuse"))

    def _wait_for_rate_limit(self, response: requests.Response, url: str) -> None:
        retry_after = response.headers.get("Retry-After")
        reset_at: str | None = None
        if retry_after:
            sleep_seconds = float(retry_after)
        else:
            reset_header = response.headers.get("X-RateLimit-Reset")
            if reset_header:
                reset_time = datetime.fromtimestamp(int(reset_header), tz=timezone.utc)
                reset_at = reset_time.isoformat()
                sleep_seconds = max(0.0, (reset_time - self.now_fn()).total_seconds()) + 2.0
            else:
                sleep_seconds = 60.0
        logging.getLogger(__name__).warning(
            "GitHub rate limit hit; sleeping %.1f seconds before retrying", sleep_seconds
        )
        self.rate_limit_events.append(
            GitHubRateLimitEvent(
                url=url,
                status_code=response.status_code,
                slept_seconds=sleep_seconds,
                reset_at=reset_at,
            )
        )
        self.sleep_fn(sleep_seconds)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Grade GitHub repositories by CI maturity.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--owner",
        default=argparse.SUPPRESS,
        help="GitHub user or organization login.",
    )
    parser.add_argument(
        "--token-env", default=DEFAULT_TOKEN_ENV, help="Environment variable containing a GitHub token."
    )
    parser.add_argument("--exclude-repos", default="", help="Comma separated repository names to skip.")
    parser.add_argument(
        "--exclude-patterns", default="", help="Comma separated fnmatch patterns for repo names to skip."
    )
    parser.add_argument("--include-archived", action="store_true", help="Include archived repositories.")
    parser.add_argument("--active-days", type=int, default=90, help="Recent workflow-run window for active CI.")
    parser.add_argument("--format", choices=["table", "json", "csv"], default="table", help="Output format.")
    parser.add_argument("--output", help="Write JSON or CSV output to this file.")
    parser.add_argument("--cache-file", default=DEFAULT_CACHE_FILE, help="Incremental cache file for per-repo results.")
    parser.add_argument(
        "--force-fresh", action="store_true", help="Ignore any existing cache and refetch all repositories."
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging.")
    return parser


def parse_csv_values(raw: str | None) -> set[str]:
    if not raw:
        return set()
    return {value.strip().lower() for value in raw.split(",") if value.strip()}


def parse_patterns(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [value.strip().lower() for value in raw.split(",") if value.strip()]


def configured_agentic_patterns() -> tuple[str, ...]:
    configured = parse_patterns(os.getenv(AGENTIC_PATTERNS_ENV))
    if configured:
        return tuple(configured)
    return AGENTIC_PATTERNS


def category_patterns() -> dict[str, tuple[str, ...]]:
    return {
        "linter": LINTER_PATTERNS,
        "unit_tests": UNIT_TEST_PATTERNS,
        "smoke_integration_tests": INTEGRATION_PATTERNS,
        "agentic_ci": configured_agentic_patterns(),
    }


def normalize_repo_name(value: str) -> str:
    candidate = value.strip().lower()
    if "/" in candidate:
        return candidate.rsplit("/", 1)[1]
    return candidate


def filter_repositories(
    repositories: list[dict[str, Any]],
    *,
    excluded_repos: set[str],
    excluded_patterns: list[str],
    include_archived: bool,
) -> RepoFilterResult:
    normalized_excluded = {normalize_repo_name(repo) for repo in excluded_repos}
    included: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    for repo in repositories:
        name = str(repo.get("name") or "")
        normalized_name = name.lower()
        if repo.get("archived") and not include_archived:
            skipped.append({"name": name, "reason": "archived"})
            continue
        if normalized_name in normalized_excluded:
            skipped.append({"name": name, "reason": "excluded_repo"})
            continue
        matched_pattern = next(
            (pattern for pattern in excluded_patterns if fnmatch.fnmatch(normalized_name, pattern)), None
        )
        if matched_pattern:
            skipped.append({"name": name, "reason": f"excluded_pattern:{matched_pattern}"})
            continue
        included.append(repo)

    return RepoFilterResult(included=included, skipped=skipped)


def iso_to_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def evidence_for_patterns(text: str, patterns: Iterable[str], workflow_path: str) -> list[str]:
    normalized_text = text.lower()
    evidence = []
    for pattern in patterns:
        if pattern.lower() not in normalized_text:
            continue
        snippet = first_matching_line(text, pattern) or pattern
        evidence.append(f"{workflow_path}: {snippet.strip()[:160]}")
    return evidence


def first_matching_line(text: str, pattern: str) -> str | None:
    matcher = re.compile(re.escape(pattern), re.IGNORECASE)
    for line in text.splitlines():
        if matcher.search(line):
            return line
    return None


def grade_for_score(score: int) -> str:
    return {
        4: "top",
        3: "strong",
        2: "developing",
        1: "basic",
        0: "none",
    }.get(score, "unknown")


def score_workflows(workflows: list[dict[str, str]]) -> tuple[int, str, dict[str, list[str]]]:
    evidence: dict[str, list[str]] = {}
    for category, patterns in category_patterns().items():
        category_evidence: list[str] = []
        for workflow in workflows:
            category_evidence.extend(evidence_for_patterns(workflow["text"], patterns, workflow["path"]))
        evidence[category] = sorted(set(category_evidence))
    score = sum(1 for category_evidence in evidence.values() if category_evidence)
    return score, grade_for_score(score), evidence


def active_ci_status(
    workflows: list[dict[str, str]], latest_run: dict[str, Any] | None, active_days: int, now: datetime
) -> tuple[bool | None, str]:
    if not workflows:
        return False, "no_workflow_files"
    if latest_run and latest_run.get("_status") == "unknown":
        return None, latest_run.get("reason", "workflow_runs_inaccessible")
    if latest_run is None:
        return False, "no_workflow_runs"

    run_time = iso_to_datetime(latest_run.get("updated_at") or latest_run.get("created_at"))
    if run_time is None:
        return None, "latest_run_missing_timestamp"
    if now - run_time <= timedelta(days=active_days):
        return True, f"latest_run_within_{active_days}_days"
    return False, f"latest_run_older_than_{active_days}_days"


def analyze_repository(
    client: GitHubClient,
    owner: str,
    repo: dict[str, Any],
    *,
    active_days: int,
    now: datetime,
) -> dict[str, Any]:
    name = repo["name"]
    workflows = client.workflow_files(owner, name, repo.get("default_branch"))
    latest_run = client.latest_workflow_run(owner, name)
    score, grade, evidence = score_workflows(workflows)
    active_status, active_reason = active_ci_status(workflows, latest_run, active_days, now)
    latest_run_at = None
    if latest_run and not latest_run.get("_status"):
        latest_run_at = latest_run.get("updated_at") or latest_run.get("created_at")

    return {
        "name": repo.get("full_name") or f"{owner}/{name}",
        "repo": name,
        "url": repo.get("html_url", ""),
        "archived": bool(repo.get("archived")),
        "private": bool(repo.get("private")),
        "default_branch": repo.get("default_branch"),
        "active_ci": active_status,
        "active_ci_reason": active_reason,
        "latest_workflow_run_at": latest_run_at,
        "workflow_file_count": len(workflows),
        "score": score,
        "grade": grade,
        "evidence": evidence,
    }


def load_cache(path: str, *, force_fresh: bool, owner: str, active_days: int) -> dict[str, Any]:
    if force_fresh or not path:
        return {"repositories": {}}
    cache_path = Path(path)
    if not cache_path.exists():
        return {"repositories": {}}
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logging.getLogger(__name__).warning("Ignoring unreadable cache file: %s", path)
        return {"repositories": {}}
    if not isinstance(payload, dict):
        return {"repositories": {}}
    if payload.get("owner") != owner or payload.get("active_days") != active_days:
        return {"repositories": {}}
    payload.setdefault("repositories", {})
    return payload


def save_cache(path: str, payload: dict[str, Any]) -> None:
    if not path:
        return
    cache_path = Path(path)
    cache_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def collect_report(client: GitHubClient, args: argparse.Namespace) -> dict[str, Any]:
    repositories = client.list_repositories(args.owner)
    filter_result = filter_repositories(
        repositories,
        excluded_repos=parse_csv_values(args.exclude_repos),
        excluded_patterns=parse_patterns(args.exclude_patterns),
        include_archived=args.include_archived,
    )
    now = datetime.now(timezone.utc)
    cache = load_cache(args.cache_file, force_fresh=args.force_fresh, owner=args.owner, active_days=args.active_days)
    cached_repos = cache.setdefault("repositories", {})
    results: list[dict[str, Any]] = []

    for repo in filter_result.included:
        full_name = repo.get("full_name") or f"{args.owner}/{repo['name']}"
        if full_name in cached_repos:
            logging.getLogger(__name__).info("Using cached result for %s", full_name)
            results.append(cached_repos[full_name])
            continue
        logging.getLogger(__name__).info("Analyzing %s", full_name)
        result = analyze_repository(client, args.owner, repo, active_days=args.active_days, now=now)
        cached_repos[full_name] = result
        results.append(result)
        cache.update({"owner": args.owner, "active_days": args.active_days, "updated_at": now.isoformat()})
        save_cache(args.cache_file, cache)

    results.sort(key=lambda item: (-int(item["score"]), item["name"].lower()))
    return {
        "owner": args.owner,
        "auth_source": client.auth_source,
        "active_days": args.active_days,
        "repository_count": len(results),
        "skipped": filter_result.skipped,
        "repositories": results,
        "rate_limit_events": [event.__dict__ for event in client.rate_limit_events],
    }


def render_table(report: dict[str, Any]) -> str:
    lines = [
        f"CI maturity for {report['owner']} ({report['repository_count']} repositories)",
        "score grade      active  repo",
        "----- ---------- ------- ----------------------------------------",
    ]
    for repo in report["repositories"]:
        active = "unknown" if repo["active_ci"] is None else str(bool(repo["active_ci"])).lower()
        lines.append(f"{repo['score']}/4   {repo['grade']:<10} {active:<7} {repo['name']}")
    if report["skipped"]:
        lines.append("")
        lines.append(f"Skipped repositories: {len(report['skipped'])}")
        for skipped in report["skipped"]:
            lines.append(f"- {skipped['name']}: {skipped['reason']}")
    return "\n".join(lines)


def render_csv(report: dict[str, Any], output_file: Any) -> None:
    writer = csv.DictWriter(
        output_file,
        fieldnames=[
            "name",
            "score",
            "grade",
            "active_ci",
            "active_ci_reason",
            "latest_workflow_run_at",
            "workflow_file_count",
            "linter",
            "unit_tests",
            "smoke_integration_tests",
            "agentic_ci",
        ],
    )
    writer.writeheader()
    for repo in report["repositories"]:
        evidence = repo["evidence"]
        writer.writerow(
            {
                "name": repo["name"],
                "score": repo["score"],
                "grade": repo["grade"],
                "active_ci": repo["active_ci"],
                "active_ci_reason": repo["active_ci_reason"],
                "latest_workflow_run_at": repo["latest_workflow_run_at"],
                "workflow_file_count": repo["workflow_file_count"],
                "linter": bool(evidence["linter"]),
                "unit_tests": bool(evidence["unit_tests"]),
                "smoke_integration_tests": bool(evidence["smoke_integration_tests"]),
                "agentic_ci": bool(evidence["agentic_ci"]),
            }
        )


def emit_report(report: dict[str, Any], *, output_format: str, output_path: str | None) -> None:
    if output_format == "json":
        rendered = json.dumps(report, indent=2, sort_keys=True)
        if output_path:
            Path(output_path).write_text(rendered + "\n", encoding="utf-8")
        else:
            print(rendered)
        return

    if output_format == "csv":
        if output_path:
            with open(output_path, "w", encoding="utf-8", newline="") as output_file:
                render_csv(report, output_file)
        else:
            render_csv(report, sys.stdout)
        return

    rendered = render_table(report)
    if output_path:
        Path(output_path).write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


def load_token(token_env: str) -> str:
    token = os.getenv(token_env)
    if not token:
        raise RuntimeError(f"Environment variable {token_env} is not set.")
    return token.strip()


def main() -> None:
    parser = build_argument_parser()
    args = parser.parse_args()
    if not getattr(args, "owner", None):
        args.owner = os.getenv("GITHUB_METRIC_OWNER_OR_ORGANIZATION")
    if not args.owner:
        parser.error("GitHub owner missing. Provide --owner or set GITHUB_METRIC_OWNER_OR_ORGANIZATION.")

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        token = load_token(args.token_env)
        client = GitHubClient(token, auth_source=f"env:{args.token_env}")
        report = collect_report(client, args)
        emit_report(report, output_format=args.format, output_path=args.output)
    except Exception as exc:  # pylint: disable=broad-except
        logging.getLogger(__name__).error("%s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
