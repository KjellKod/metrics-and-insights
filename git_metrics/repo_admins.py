"""
repo_admins.py
----------------

Discover who has specific GitHub repository permissions (users and teams)
across an organization. The script talks directly to the GitHub GraphQL and
REST APIs, handles pagination automatically, and summarizes the results so you
can quickly see which accounts have the requested access level.

Example:
    python git_metrics/repo_admins.py --org myOrg --token-env GITHUB_TOKEN_READONLY_WEB
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Dict, List, Optional

import requests
from dotenv import load_dotenv


load_dotenv()

GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"
GITHUB_REST_URL = "https://api.github.com"

PERMISSION_ALIASES = {
    "READ": "READ",
    "PULL": "READ",
    "TRIAGE": "TRIAGE",
    "WRITE": "WRITE",
    "PUSH": "WRITE",
    "MAINTAIN": "MAINTAIN",
    "ADMIN": "ADMIN",
    "ALL": "ALL",
}

VALID_PERMISSIONS = {"READ", "TRIAGE", "WRITE", "MAINTAIN", "ADMIN"}

REPOSITORY_LIST_QUERY = """
query($org: String!, $cursor: String) {
  organization(login: $org) {
    repositories(first: 50, after: $cursor, orderBy: {field: NAME, direction: ASC}) {
      nodes {
        name
        nameWithOwner
        url
        isPrivate
        isArchived
      }
      pageInfo {
        hasNextPage
        endCursor
      }
    }
  }
}
"""

REPOSITORY_PERMISSION_QUERY = """
query($owner: String!, $name: String!, $collCursor: String) {
  repository(owner: $owner, name: $name) {
    collaborators(first: 100, after: $collCursor) {
      edges {
        permission
        node {
          login
          name
          url
        }
      }
      pageInfo {
        hasNextPage
        endCursor
      }
    }
  }
}
"""


class GitHubClient:
    """Minimal GraphQL client for GitHub."""

    def __init__(self, token: str):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            }
        )

    def query(self, query_text: str, variables: Dict[str, Optional[str]]) -> Dict:
        response = self.session.post(
            GITHUB_GRAPHQL_URL,
            json={"query": query_text, "variables": variables},
            timeout=90,
        )

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as exc:  # pragma: no cover - pass through with context
            raise RuntimeError(f"GitHub GraphQL request failed: {exc} -> {response.text}") from exc

        payload = response.json()
        if "errors" in payload:
            raise RuntimeError(f"GitHub GraphQL errors: {payload['errors']}")

        return payload.get("data", {})

    def rest_get(self, url: str, params: Optional[Dict[str, int]] = None) -> requests.Response:
        response = self.session.get(url, params=params, timeout=90)
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as exc:  # pragma: no cover - pass through with context
            raise RuntimeError(f"GitHub REST request failed: {exc} -> {response.text}") from exc
        return response


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="List all user and team admins for repositories in a GitHub organization.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--org",
        default=os.getenv("GITHUB_METRIC_OWNER_OR_ORGANIZATION"),
        help="GitHub organization login (falls back to GITHUB_METRIC_OWNER_OR_ORGANIZATION).",
    )
    parser.add_argument(
        "--token-env",
        default="GITHUB_TOKEN_READONLY_WEB",
        help="Environment variable that stores the GitHub token to use.",
    )
    parser.add_argument(
        "--repos",
        help="Optional comma separated list of repository names (or owner/name) to inspect.",
    )
    parser.add_argument(
        "--include-archived",
        action="store_true",
        help="Include archived repositories.",
    )
    parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Only print the aggregated summary (skip per-repository details).",
    )
    parser.add_argument(
        "--permissions",
        help="Comma separated permissions to include (e.g. 'admin,write,read'). Defaults to 'admin'.",
        default="admin",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging.",
    )

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args()

    if not args.org:
        parser.error("GitHub organization missing. Provide --org or set GITHUB_METRIC_OWNER_OR_ORGANIZATION.")

    return args


def parse_permissions(raw: str) -> set[str]:
    if not raw:
        return {"ADMIN"}

    requested: set[str] = set()
    for token in raw.split(","):
        label = token.strip().upper()
        if not label:
            continue
        alias = PERMISSION_ALIASES.get(label)
        if alias is None:
            raise ValueError(
                f"Unknown permission '{token}'. Supported values: read/pull, triage, write/push, maintain, admin."
            )
        if alias == "ALL":
            return set(VALID_PERMISSIONS)
        requested.add(alias)

    if not requested:
        return {"ADMIN"}

    unknown = requested - VALID_PERMISSIONS
    if unknown:
        raise ValueError(f"Unsupported permissions requested: {', '.join(sorted(unknown))}")

    return requested


def load_token(env_var: str) -> str:
    token = os.getenv(env_var)
    if not token:
        raise RuntimeError(f"Environment variable {env_var} is not set.")
    return token.strip()


def parse_repo_filters(raw_repos: Optional[str], owner: str) -> Optional[set[str]]:
    if not raw_repos:
        return None

    repo_names: set[str] = set()
    for raw in raw_repos.split(","):
        candidate = raw.strip()
        if not candidate:
            continue
        candidate_lower = candidate.lower()
        if "/" in candidate_lower:
            repo_owner, repo_name = candidate_lower.split("/", 1)
            if repo_owner != owner.lower():
                raise ValueError(
                    f"Repository '{candidate}' does not belong to owner '{owner}'. "
                    "Please specify repositories inside the same organization."
                )
            repo_names.add(repo_name)
        else:
            repo_names.add(candidate_lower)
    return repo_names


def fetch_repositories(
    client: GitHubClient,
    owner: str,
    include_archived: bool,
    repo_filter: Optional[set[str]],
) -> List[Dict]:
    logger = logging.getLogger(__name__)
    repos: List[Dict] = []
    cursor: Optional[str] = None
    has_next = True

    while has_next:
        data = client.query(REPOSITORY_LIST_QUERY, {"org": owner, "cursor": cursor})
        org_data = data.get("organization")
        if org_data is None:
            raise RuntimeError(f"Organization '{owner}' not found or inaccessible.")

        repo_nodes = org_data["repositories"]["nodes"]
        for node in repo_nodes:
            if node["isArchived"] and not include_archived:
                continue
            if repo_filter and node["name"].lower() not in repo_filter:
                continue
            repos.append(node)

        page_info = org_data["repositories"]["pageInfo"]
        has_next = page_info["hasNextPage"]
        cursor = page_info["endCursor"]
        logger.debug("Fetched %d repositories so far...", len(repos))

        if repo_filter and not has_next:
            # We either collected all filtered repos or the filter references unknown repos.
            missing = repo_filter - {repo["name"].lower() for repo in repos}
            if missing:
                raise RuntimeError(f"Repositories not found inside '{owner}': {', '.join(sorted(missing))}")

    return repos


def fetch_repo_admins(
    client: GitHubClient,
    owner: str,
    repo_name: str,
    permissions: set[str],
) -> Dict[str, List[Dict[str, str]]]:
    user_admins: Dict[str, Dict[str, str]] = {}

    coll_cursor: Optional[str] = None
    more_collaborators = True

    while more_collaborators:
        variables = {
            "owner": owner,
            "name": repo_name,
            "collCursor": coll_cursor,
        }
        data = client.query(REPOSITORY_PERMISSION_QUERY, variables)
        repo_data = data.get("repository")
        if repo_data is None:
            raise RuntimeError(f"Repository '{owner}/{repo_name}' not found or inaccessible.")

        collaborators = repo_data.get("collaborators")
        if collaborators:
            for edge in collaborators.get("edges", []):
                permission = (edge.get("permission") or "").upper()
                if permission not in permissions:
                    continue
                node = edge.get("node") or {}
                login = node.get("login")
                if not login:
                    continue
                user_admins[login] = {
                    "login": login,
                    "name": node.get("name") or "",
                    "url": node.get("url") or "",
                    "permission": permission,
                }

            coll_page_info = collaborators.get("pageInfo") or {}
            more_collaborators = bool(coll_page_info.get("hasNextPage"))
            coll_cursor = coll_page_info.get("endCursor") if more_collaborators else None
        else:
            more_collaborators = False
            coll_cursor = None

    team_admins = fetch_repo_teams(client, owner, repo_name, permissions)

    return {
        "users": sorted(user_admins.values(), key=lambda item: item["login"].lower()),
        "teams": sorted(team_admins.values(), key=lambda item: item["slug"].lower()),
    }


def fetch_repo_teams(
    client: GitHubClient,
    owner: str,
    repo_name: str,
    permissions: set[str],
) -> Dict[str, Dict[str, str]]:
    logger = logging.getLogger(__name__)
    teams: Dict[str, Dict[str, str]] = {}
    url = f"{GITHUB_REST_URL}/repos/{owner}/{repo_name}/teams"
    params: Optional[Dict[str, int]] = {"per_page": 100}

    while url:
        try:
            response = client.rest_get(url, params=params)
        except RuntimeError as exc:
            logger.warning("Unable to fetch teams for %s/%s: %s", owner, repo_name, exc)
            break

        data = response.json()
        for team in data:
            slug = team.get("slug")
            if not slug:
                continue
            permission_raw = (team.get("permission") or "").upper()
            permission = PERMISSION_ALIASES.get(permission_raw, permission_raw)
            if permission not in permissions:
                continue
            teams[slug] = {
                "slug": slug,
                "name": team.get("name") or "",
                "url": team.get("html_url") or team.get("url") or "",
                "organization": (team.get("organization") or {}).get("login") or owner,
                "permission": permission,
            }

        if "next" in response.links:
            url = response.links["next"]["url"]
            params = None
        else:
            url = None

    return teams


def render_table(report: List[Dict], summary: Dict[str, List[Dict]]) -> None:
    def format_people(items: List[Dict], label_key: str) -> str:
        if not items:
            return "none"
        formatted = []
        for item in items:
            label = item.get(label_key, "")
            name = item.get("name") or item.get("login") or item.get("slug") or ""
            display = label
            if name and name.lower() != label.lower():
                display = f"{label} ({name})"
            permission = item.get("permission")
            if permission:
                display = f"{display} [{permission.lower()}]"
            formatted.append(display)
        return ", ".join(formatted)

    for repo in report:
        qualifiers = []
        if repo["isPrivate"]:
            qualifiers.append("private")
        if repo["isArchived"]:
            qualifiers.append("archived")
        qualifier_text = f" [{' | '.join(qualifiers)}]" if qualifiers else ""

        print(f"{repo['nameWithOwner']}{qualifier_text}")
        print(f"  url            : {repo['url']}")
        print(f"  matching users : {format_people(repo['userAdmins'], 'login')}")
        print(f"  matching teams : {format_people(repo['teamAdmins'], 'slug')}")
        print()


def print_summary(summary: Dict[str, List[Dict]]) -> None:
    print("== Aggregated permission coverage ==")
    if summary["users"]:
        print("Users:")
        for entry in summary["users"]:
            repos = ", ".join(
                f"{repo['name']} ({repo['permission'].lower()})" if repo["permission"] else repo["name"]
                for repo in entry["repositories"]
            )
            print(f"  {entry['login']} ({entry['repoCount']} repos): {repos}")
    else:
        print("Users: none found.")

    if summary["teams"]:
        print("\nTeams:")
        for entry in summary["teams"]:
            repos = ", ".join(
                f"{repo['name']} ({repo['permission'].lower()})" if repo["permission"] else repo["name"]
                for repo in entry["repositories"]
            )
            label = f"{entry['organization']}/{entry['slug']}"
            print(f"  {label} ({entry['repoCount']} repos): {repos}")
    else:
        print("\nTeams: none found.")


def build_summary(report: List[Dict]) -> Dict[str, List[Dict]]:
    user_map: Dict[str, Dict] = {}
    team_map: Dict[str, Dict] = {}

    for repo in report:
        repo_name = repo["nameWithOwner"]
        for user in repo["userAdmins"]:
            login = user["login"]
            user_entry = user_map.setdefault(
                login,
                {
                    "login": login,
                    "name": user.get("name", ""),
                    "url": user.get("url", ""),
                    "repositories": [],
                },
            )
            user_entry["repositories"].append({"name": repo_name, "permission": user.get("permission", "")})

        for team in repo["teamAdmins"]:
            slug = team["slug"]
            team_entry = team_map.setdefault(
                slug,
                {
                    "slug": slug,
                    "name": team.get("name", ""),
                    "organization": team.get("organization", ""),
                    "url": team.get("url", ""),
                    "repositories": [],
                },
            )
            team_entry["repositories"].append({"name": repo_name, "permission": team.get("permission", "")})

    def finalize(entries: Dict[str, Dict], id_key: str) -> List[Dict]:
        for item in entries.values():
            item["repositories"] = sorted(item["repositories"], key=lambda repo: repo["name"])
            item["repoCount"] = len(item["repositories"])
        return sorted(entries.values(), key=lambda value: (-value["repoCount"], value[id_key]))

    return {
        "users": finalize(user_map, "login"),
        "teams": finalize(team_map, "slug"),
    }


def build_json_output(
    report: List[Dict],
    summary: Dict[str, List[Dict]],
    requested_permissions: set[str],
) -> Dict[str, Dict]:
    repositories: List[Dict] = []
    for repo in report:
        users = sorted({user["login"] for user in repo["userAdmins"]})
        teams = sorted(
            {
                f"{team['organization']}/{team['slug']}"
                if team.get("organization")
                else team["slug"]
                for team in repo["teamAdmins"]
            }
        )
        repositories.append(
            {
                "name": repo["nameWithOwner"],
                "users": users,
                "teams": teams,
            }
        )

    return {
        "requestedPermissions": sorted(requested_permissions),
        "repositories": repositories,
        "summary": summary,
    }


def main() -> None:
    args = parse_arguments()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger(__name__)

    try:
        token = load_token(args.token_env)
    except RuntimeError as exc:
        logger.error("%s", exc)
        sys.exit(1)

    try:
        permissions = parse_permissions(args.permissions)
    except ValueError as exc:
        logger.error("%s", exc)
        sys.exit(1)

    try:
        repo_filter = parse_repo_filters(args.repos, args.org)
    except ValueError as exc:
        logger.error("%s", exc)
        sys.exit(1)

    client = GitHubClient(token)

    try:
        repositories = fetch_repositories(client, args.org, args.include_archived, repo_filter)
    except RuntimeError as exc:
        logger.error("%s", exc)
        sys.exit(1)

    if not repositories:
        logger.warning("No repositories matched the provided criteria.")
        sys.exit(0)

    report: List[Dict] = []

    for idx, repo in enumerate(repositories, start=1):
        logger.info("Scanning permissions for %s (%d/%d)", repo["nameWithOwner"], idx, len(repositories))
        try:
            admins = fetch_repo_admins(client, args.org, repo["name"], permissions)
        except RuntimeError as exc:
            logger.error("Failed to fetch collaborators for %s: %s", repo["nameWithOwner"], exc)
            continue

        report.append(
            {
                "nameWithOwner": repo["nameWithOwner"],
                "name": repo["name"],
                "url": repo["url"],
                "isPrivate": repo["isPrivate"],
                "isArchived": repo["isArchived"],
                "userAdmins": admins["users"],
                "teamAdmins": admins["teams"],
            }
        )

    summary = build_summary(report)

    if args.format == "json":
        output = build_json_output(report, summary, permissions)
        print(json.dumps(output, indent=2))
        return

    if not args.summary_only:
        render_table(report, summary)
    print_summary(summary)


if __name__ == "__main__":
    main()
