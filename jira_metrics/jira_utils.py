import argparse
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

import requests
from dotenv import load_dotenv
from gql import Client, gql
from gql.transport.requests import RequestsHTTPTransport
from jira import JIRA

# Raw Jira JSON is intentionally dynamic only at this deserialization boundary.
# pylint: disable=too-many-lines

load_dotenv()

# ==============================================================================
# CONFIGURABLE COMPLETION AND EXCLUDED STATUSES
# ==============================================================================
# By default, tickets are considered "done" when they reach "released" or "done" status.
# You can customize which statuses count as completion by setting the COMPLETION_STATUSES
# environment variable in your .env file.
#
# Example in .env:
#   COMPLETION_STATUSES=released,done,to release,staged release
#
# This affects cycle time calculations, individual metrics, and all other scripts
# that use get_completion_statuses() or interpret_status_timestamps().
#
# Additionally, you can exclude certain statuses (like "closed", "cancelled") that shouldn't
# count as either Done (no credit to team) or Open (not open work):
#
#   EXCLUDED_STATUSES=closed,cancelled,duplicate
#
# Status names are case-insensitive and whitespace is trimmed.
# # ==============================================================================


# Access the custom field IDs
CUSTOM_FIELD_TEAM = os.getenv("CUSTOM_FIELD_TEAM")
CUSTOM_FIELD_WORK_TYPE = os.getenv("CUSTOM_FIELD_WORK_TYPE")
CUSTOM_FIELD_STORYPOINTS = os.getenv("CUSTOM_FIELD_STORYPOINTS")

# Global variable for verbosity
VERBOSE = False

# Cache for completion statuses to avoid repeated prints
_COMPLETION_STATUSES_CACHE = None
_EXCLUDED_STATUSES_CACHE = None


def reset_status_caches():
    """Reset cached completion and excluded statuses (useful for tests)."""
    global _COMPLETION_STATUSES_CACHE, _EXCLUDED_STATUSES_CACHE
    _COMPLETION_STATUSES_CACHE = None
    _EXCLUDED_STATUSES_CACHE = None


def verbose_print(message):
    if VERBOSE:
        print(message)


class JiraStatus(Enum):
    CODE_REVIEW = "code review"
    RELEASED = "released"
    DONE = "done"


@dataclass(frozen=True)
class StatusTransition:
    status: str
    timestamp: datetime


@dataclass(frozen=True)
class TimeInStatusResult:
    issue_id: str
    saw_status: bool
    completed_intervals: int
    total_seconds: float
    last_exit_timestamp: datetime | None
    open_start_timestamp: datetime | None


@dataclass(frozen=True)
class JiraSearchResult:
    """Raw Jira issue search pages plus completeness diagnostics."""

    issues: list[dict[str, Any]]
    complete: bool
    limitations: list[str] = field(default_factory=list)
    page_count: int = 0


@dataclass(frozen=True)
class JiraFieldResult:
    """Jira field metadata plus completeness diagnostics."""

    fields: list[dict[str, Any]]
    complete: bool
    limitations: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ChangelogFetchResult:
    """Complete raw changelogs grouped by issue key."""

    records_by_issue: dict[str, list[dict[str, Any]]]
    method: str
    complete: bool
    limitations: list[str] = field(default_factory=list)
    page_count: int = 0


def _jira_rest_config() -> tuple[str, tuple[str, str], dict[str, str]]:
    """Return validated Jira REST configuration without exposing its values."""
    jira_link = os.environ.get("JIRA_LINK")
    user_email = os.environ.get("USER_EMAIL")
    api_key = os.environ.get("JIRA_API_KEY")
    missing = [
        name
        for name, value in (("JIRA_LINK", jira_link), ("USER_EMAIL", user_email), ("JIRA_API_KEY", api_key))
        if not value
    ]
    if missing:
        raise ValueError(f"Missing required Jira environment variables: {', '.join(missing)}")

    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    return jira_link.rstrip("/"), (user_email, api_key), headers


def _request_jira_json(method, url, *, auth, headers, params=None, payload=None):  # pylint: disable=too-many-arguments
    """Request a Jira JSON page with bounded retries and sanitized failures."""
    request = requests.get if method == "GET" else requests.post
    response = None
    for attempt in range(5):
        try:
            kwargs = {"auth": auth, "headers": headers, "timeout": 30}
            if params is not None:
                kwargs["params"] = params
            if payload is not None:
                kwargs["json"] = payload
            response = request(url, **kwargs)
        except requests.exceptions.RequestException:
            if attempt == 4:
                return None, None, f"{method} request failed after retries"
            time.sleep(min(2**attempt, 10))
            continue

        if response.status_code in (429, 500, 502, 503, 504) and attempt < 4:
            time.sleep(min(2**attempt, 10))
            continue
        if response.status_code != 200:
            return None, response.status_code, f"{method} request returned status {response.status_code}"
        try:
            return response.json(), response.status_code, None
        except ValueError:
            return None, response.status_code, f"{method} request returned invalid JSON"

    return None, getattr(response, "status_code", None), f"{method} request failed"


def search_jira_issues_raw(  # pylint: disable=too-many-locals,too-many-return-statements
    jql: str, fields: list[str]
) -> JiraSearchResult:
    """Return all raw issues from Jira's token-paginated v3 search endpoint."""
    jira_link, auth, headers = _jira_rest_config()
    endpoint = f"{jira_link}/rest/api/3/search/jql"
    issues: list[dict[str, Any]] = []
    limitations: list[str] = []
    next_page_token = None
    seen_tokens: set[str] = set()
    page_count = 0

    while True:
        params = {"jql": jql, "fields": ",".join(fields), "maxResults": 100}
        if next_page_token:
            params["nextPageToken"] = next_page_token
        data, _, error = _request_jira_json("GET", endpoint, auth=auth, headers=headers, params=params)
        if error:
            limitations.append(f"Candidate search page {page_count + 1} failed: {error}.")
            return JiraSearchResult(issues, False, limitations, page_count)
        page_count += 1
        if not isinstance(data, dict):
            limitations.append(f"Candidate search page {page_count} had an unexpected response shape.")
            return JiraSearchResult(issues, False, limitations, page_count)

        page_issues = data.get("issues", [])
        if not isinstance(page_issues, list):
            limitations.append(f"Candidate search page {page_count} did not contain an issue list.")
            return JiraSearchResult(issues, False, limitations, page_count)
        if any(not isinstance(issue, dict) for issue in page_issues):
            limitations.append(f"Candidate search page {page_count} contained an invalid issue entry.")
            return JiraSearchResult(issues, False, limitations, page_count)
        issues.extend(page_issues)

        token = data.get("nextPageToken")
        if token:
            token = str(token)
            if token in seen_tokens:
                limitations.append("Candidate search returned a repeated next-page token.")
                return JiraSearchResult(issues, False, limitations, page_count)
            seen_tokens.add(token)
            next_page_token = token
            continue
        if data.get("isLast", True):
            return JiraSearchResult(issues, True, limitations, page_count)
        limitations.append("Candidate search ended before Jira marked the final page.")
        return JiraSearchResult(issues, False, limitations, page_count)


def get_jira_field_metadata() -> JiraFieldResult:
    """Fetch raw Jira field metadata used to discover relationship field IDs."""
    jira_link, auth, headers = _jira_rest_config()
    data, _, error = _request_jira_json("GET", f"{jira_link}/rest/api/3/field", auth=auth, headers=headers)
    if error:
        return JiraFieldResult([], False, [f"Jira field metadata retrieval failed: {error}."])
    if not isinstance(data, list):
        return JiraFieldResult([], False, ["Jira field metadata had an unexpected response shape."])
    if any(not isinstance(item, dict) for item in data):
        return JiraFieldResult(
            [item for item in data if isinstance(item, dict)],
            False,
            ["Jira field metadata contained an invalid field entry."],
        )
    return JiraFieldResult(data, True)


def _history_identity(history: dict[str, Any]) -> str:
    """Return a deterministic identity for exact raw-history deduplication."""
    return json.dumps(history, sort_keys=True, separators=(",", ":"), default=str)


def _merge_history_records(target: list[dict[str, Any]], additions: list[dict[str, Any]]) -> None:
    identities = {_history_identity(record) for record in target}
    for record in additions:
        identity = _history_identity(record)
        if identity not in identities:
            target.append(record)
            identities.add(identity)


def _validate_changelog_page_range(
    data: dict[str, Any], requested_start: int, value_count: int
) -> tuple[int, str | None]:
    """Validate Jira pagination metadata and return the proven page end."""
    response_start = data.get("startAt")
    if not isinstance(response_start, int) or isinstance(response_start, bool) or response_start != requested_start:
        returned_start = response_start if isinstance(response_start, int) else "missing or invalid"
        return (
            requested_start,
            f"requested startAt {requested_start} but Jira returned {returned_start}; "
            "pagination did not make reliable forward progress",
        )

    total = data.get("total")
    if total is not None and (not isinstance(total, int) or isinstance(total, bool) or total < 0):
        return requested_start, "returned invalid total pagination metadata"

    is_last = data.get("isLast")
    if is_last is not None and not isinstance(is_last, bool):
        return requested_start, "returned invalid isLast pagination metadata"

    page_end = response_start + value_count
    if isinstance(total, int):
        terminal_conflict = (is_last is True and page_end != total) or (is_last is False and page_end >= total)
        if page_end > total or terminal_conflict:
            return (
                requested_start,
                "returned contradictory pagination metadata: "
                f"isLast={is_last}, page range {response_start}:{page_end}, total={total}",
            )
    return page_end, None


def _fetch_issue_changelog(  # pylint: disable=too-many-locals,too-many-return-statements
    issue_key: str, jira_link, auth, headers
):
    endpoint = f"{jira_link}/rest/api/3/issue/{issue_key}/changelog"
    records: list[dict[str, Any]] = []
    start_at = 0
    page_count = 0

    while True:
        params = {"startAt": start_at, "maxResults": 100}
        data, _, error = _request_jira_json("GET", endpoint, auth=auth, headers=headers, params=params)
        if error:
            return records, False, page_count, f"Changelog fallback for {issue_key} failed: {error}."
        page_count += 1
        if not isinstance(data, dict) or not isinstance(data.get("values", []), list):
            return records, False, page_count, f"Changelog fallback for {issue_key} had an unexpected response shape."
        raw_values = data.get("values", [])
        if any(not isinstance(item, dict) for item in raw_values):
            return records, False, page_count, f"Changelog fallback for {issue_key} had an invalid history entry."
        values = list(raw_values)
        _merge_history_records(records, values)

        page_end, pagination_error = _validate_changelog_page_range(data, start_at, len(values))
        if pagination_error:
            return records, False, page_count, f"Changelog fallback for {issue_key} {pagination_error}."
        total = data.get("total")
        is_last = data.get("isLast")
        if is_last is True:
            return records, True, page_count, None
        if isinstance(total, int) and page_end == total:
            return records, True, page_count, None
        if not values:
            return (
                records,
                False,
                page_count,
                f"Changelog fallback for {issue_key} ended before the final page and made no forward progress.",
            )
        if is_last is None and not isinstance(total, int):
            return (
                records,
                False,
                page_count,
                f"Changelog fallback for {issue_key} did not provide reliable pagination termination.",
            )
        start_at = page_end


def _bulk_page_records(data, id_to_key):
    """Extract issue-keyed histories from one bulk changelog page."""
    containers = data.get("issueChangeLogs", []) if isinstance(data, dict) else []
    if not isinstance(containers, list):
        return None
    page_records: dict[str, list[dict[str, Any]]] = {}
    confirmed: set[str] = set()
    for container in containers:
        if not isinstance(container, dict):
            return None
        raw_identity = container.get("issueId") or container.get("issueKey")
        if raw_identity is None:
            return None
        identity = str(raw_identity)
        issue_key = id_to_key.get(identity, identity)
        histories = container.get("changeHistories", [])
        if not isinstance(histories, list) or any(not isinstance(item, dict) for item in histories):
            return None
        confirmed.add(issue_key)
        page_records.setdefault(issue_key, []).extend(histories)
    return page_records, confirmed


def fetch_complete_changelogs(  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
    issue_ids_or_keys: list[str], id_to_key: dict[str, str] | None = None
) -> ChangelogFetchResult:
    """Fetch complete raw changelogs using bulk pages with per-issue fallback."""
    if not issue_ids_or_keys:
        return ChangelogFetchResult({}, "bulk", True)

    jira_link, auth, headers = _jira_rest_config()
    endpoint = f"{jira_link}/rest/api/3/changelog/bulkfetch"
    lookup = dict(id_to_key or {})
    requested_keys = {lookup.get(value, value) for value in issue_ids_or_keys}
    records_by_issue = {key: [] for key in requested_keys}
    limitations: list[str] = []
    methods: set[str] = set()
    complete = True
    page_count = 0
    bulk_supported = True

    for offset in range(0, len(issue_ids_or_keys), 1000):
        batch = issue_ids_or_keys[offset : offset + 1000]
        batch_keys = {lookup.get(value, value) for value in batch}
        confirmed: set[str] = set()
        batch_failed = False
        next_page_token = None
        seen_tokens: set[str] = set()

        if bulk_supported:
            while True:
                payload = {"issueIdsOrKeys": batch, "maxResults": 1000}
                if next_page_token:
                    payload["nextPageToken"] = next_page_token
                data, status, error = _request_jira_json("POST", endpoint, auth=auth, headers=headers, payload=payload)
                if error:
                    if status in (400, 404, 405):
                        bulk_supported = False
                        limitations.append(
                            "Bulk changelog retrieval is unavailable; complete per-issue fallback was used."
                        )
                    else:
                        complete = False
                        limitations.append(f"Bulk changelog page failed: {error}; per-issue fallback was attempted.")
                    batch_failed = True
                    break
                methods.add("bulk")
                page_count += 1
                extracted = _bulk_page_records(data, lookup)
                if extracted is None:
                    complete = False
                    limitations.append(
                        "Bulk changelog page had an unexpected response shape; per-issue fallback was attempted."
                    )
                    batch_failed = True
                    break
                page_records, page_confirmed = extracted
                confirmed.update(page_confirmed)
                for issue_key, histories in page_records.items():
                    records_by_issue.setdefault(issue_key, [])
                    _merge_history_records(records_by_issue[issue_key], histories)

                token = data.get("nextPageToken") if isinstance(data, dict) else None
                if not token:
                    break
                token = str(token)
                if token in seen_tokens:
                    complete = False
                    limitations.append("Bulk changelog retrieval returned a repeated next-page token.")
                    batch_failed = True
                    break
                seen_tokens.add(token)
                next_page_token = token
        else:
            batch_failed = True

        fallback_keys = batch_keys if batch_failed else batch_keys - confirmed
        if fallback_keys and not batch_failed:
            limitations.append(
                "Bulk changelog response omitted requested issues; complete per-issue fallback was used for those issues."
            )
        for issue_key in sorted(fallback_keys):
            methods.add("per-issue fallback")
            histories, issue_complete, fallback_pages, limitation = _fetch_issue_changelog(
                issue_key, jira_link, auth, headers
            )
            page_count += fallback_pages
            records_by_issue.setdefault(issue_key, [])
            _merge_history_records(records_by_issue[issue_key], histories)
            if not issue_complete:
                complete = False
                if limitation:
                    limitations.append(limitation)

    if methods == {"bulk"}:
        method = "bulk"
    elif methods == {"per-issue fallback"}:
        method = "per-issue fallback"
    else:
        method = "mixed bulk and per-issue fallback"
    return ChangelogFetchResult(records_by_issue, method, complete, limitations, page_count)


def get_common_parser():
    # pylint: disable=global-statement
    # Define the argument parser
    parser = argparse.ArgumentParser(description="Common script options")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output")
    parser.add_argument("-csv", action="store_true", help="Export the release data to a CSV file.")

    return parser


def parse_common_arguments(parser=None):
    if parser is None:
        parser = get_common_parser()
    global VERBOSE
    args = parser.parse_args()
    VERBOSE = args.verbose
    print(f"Verbose printing enabled: {VERBOSE}")
    return args


def get_completion_statuses():
    """
    Return the list of configured completion statuses used to determine the end of cycle time.

    Defaults to ["released", "done"]. Teams can override via the COMPLETION_STATUSES
    environment variable with a comma-separated list, e.g. "closed,done,to release,released".

    Prints configuration only on first call to avoid repetition.
    """
    global _COMPLETION_STATUSES_CACHE

    # Return cached value if available (no print on subsequent calls)
    if _COMPLETION_STATUSES_CACHE is not None:
        return _COMPLETION_STATUSES_CACHE

    # First call: parse, cache, and print
    completion_statuses_str = os.getenv("COMPLETION_STATUSES", "released,done")
    completion_statuses = [s.strip().lower() for s in completion_statuses_str.split(",") if s.strip()]
    _COMPLETION_STATUSES_CACHE = completion_statuses

    print(f"✓ Tickets will be considered DONE when status is: {completion_statuses}")
    return completion_statuses


def get_excluded_statuses():
    """
    Return the list of statuses to exclude from metrics (neither Done nor Open).

    These are tickets that shouldn't count toward completion (no credit to team)
    but also shouldn't be counted as open work. Examples: "closed", "cancelled", "duplicate".

    Defaults to ["closed"]. Teams can override via the EXCLUDED_STATUSES
    environment variable with a comma-separated list, e.g. "closed,cancelled,duplicate".

    Prints configuration only on first call to avoid repetition.
    """
    global _EXCLUDED_STATUSES_CACHE

    # Return cached value if available (no print on subsequent calls)
    if _EXCLUDED_STATUSES_CACHE is not None:
        return _EXCLUDED_STATUSES_CACHE

    # First call: parse, cache, and print
    excluded_statuses_str = os.getenv("EXCLUDED_STATUSES", "closed")
    excluded_statuses = [s.strip().lower() for s in excluded_statuses_str.split(",") if s.strip()]
    _EXCLUDED_STATUSES_CACHE = excluded_statuses

    print(f"✓ Tickets will be EXCLUDED (not counted) when status is: {excluded_statuses}")
    return excluded_statuses


def get_code_review_statuses():
    """
    Return the set of statuses considered as entering code review.

    Currently static, but centralized so callers can print and so we can
    adjust in one place later if needed.
    """
    return {
        "code review",
        "in code review",
        "to review",
        "to code review",
        "in review",
        "in design review",
    }


def get_jira_instance():
    """
    Create and verify the jira instance
    """
    required_env_vars = [
        "JIRA_API_KEY",
        "USER_EMAIL",
        "JIRA_LINK",
        "JIRA_PROJECTS",
        "CUSTOM_FIELD_TEAM",
        "CUSTOM_FIELD_WORK_TYPE",
        "CUSTOM_FIELD_STORYPOINTS",
    ]

    for var in required_env_vars:
        if os.environ.get(var) is None:
            raise ValueError(f"Environment variable {var} is not set.")

    projects = os.environ.get("JIRA_PROJECTS").split(",")
    user = os.environ.get("USER_EMAIL")
    api_key = os.environ.get("JIRA_API_KEY")
    link = os.environ.get("JIRA_LINK")

    # Debug prints to verify credentials (mask the API key for security)
    print("\nAttempting JIRA connection with:")
    print(f"Link: {link}")
    print(f"User: {user}")
    print(f"API Key length: {len(api_key)}")
    print(f"Projects: {projects}")

    if not api_key or len(api_key.strip()) == 0:
        raise ValueError("JIRA API key is empty or invalid")

    if not user or not "@" in user:
        raise ValueError("Invalid email format for USER_EMAIL")

    if not link or not link.startswith("https://"):
        raise ValueError("Invalid JIRA link format")

    # Configure for JIRA REST API v3 as per migration guidelines
    options = {
        "server": link,
        "verify": True,  # Ensure SSL verification is enabled
        "rest_api_version": "3",  # Explicitly specify v3 API
    }

    try:
        print("\nInitializing JIRA connection...")
        jira = JIRA(options=options, basic_auth=(user, api_key))

        print("Verifying authentication...")
        user_info = jira.myself()
        print(f"Successfully authenticated as: {user_info['displayName']}")

        return jira

    except Exception as e:
        print("\nAuthentication Error Details:")
        print(f"- Error Type: {type(e).__name__}")
        print(f"- Error Message: {str(e)}")
        print("\nPlease verify:")
        print("1. Your API key is correct and not expired")
        print("2. Your email address matches your Jira account")
        print("3. The Jira URL is correct")
        print("4. You have the necessary permissions in Jira")
        raise ConnectionError(f"Jira authentication failed: {str(e)}") from e


def print_env_variables():
    """
    Print Jira-related environment variables for debugging.
    """

    required_env_vars = [
        "JIRA_API_KEY",
        "USER_EMAIL",
        "JIRA_LINK",
        "JIRA_PROJECTS",
        "CUSTOM_FIELD_TEAM",
        "CUSTOM_FIELD_WORK_TYPE",
        "CUSTOM_FIELD_STORYPOINTS",
    ]

    print("\n=== Jira Environment Variables ===\n")

    for var in required_env_vars:
        value = os.environ.get(var, "NOT SET")

        # Mask sensitive information like API keys
        if "KEY" in var or "PASSWORD" in var:
            value = "****** (hidden for security)"

        print(f"{var}: {value}")


def _safe_get_nested(data, *keys, default=None):
    """Safely get nested dictionary values with fallback to default."""
    try:
        result = data
        for key in keys:
            result = result[key]
        return result
    except (KeyError, TypeError):
        return default


def _create_project_object(fields_data):
    """Create project object from fields data with error handling."""
    project_data = fields_data.get("project", {})
    if not isinstance(project_data, dict):
        verbose_print(f"Warning: Invalid project data format: {type(project_data)}")
        project_data = {}

    project = SimpleNamespace()
    project.key = project_data.get("key")
    project.name = project_data.get("name")
    return project


def _create_status_object(fields_data):
    """Create status object from fields data with error handling."""
    status_data = fields_data.get("status", {})
    if not isinstance(status_data, dict):
        verbose_print(f"Warning: Invalid status data format: {type(status_data)}")
        status_data = {}

    status = SimpleNamespace()
    status.name = status_data.get("name")
    return status


def _create_priority_object(fields_data):
    """Create priority object from fields data with error handling."""
    priority_data = fields_data.get("priority")
    if not priority_data:
        return None

    if not isinstance(priority_data, dict):
        verbose_print(f"Warning: Invalid priority data format: {type(priority_data)}")
        return None

    priority = SimpleNamespace()
    priority.name = priority_data.get("name")
    return priority


def _create_assignee_object(fields_data):
    """Create assignee object from fields data with error handling."""
    assignee_data = fields_data.get("assignee")
    if not assignee_data:
        return None

    if not isinstance(assignee_data, dict):
        verbose_print(f"Warning: Invalid assignee data format: {type(assignee_data)}")
        return None

    assignee = SimpleNamespace()
    assignee.displayName = assignee_data.get("displayName")  # pylint: disable=invalid-name
    return assignee


def _create_issue_links(fields_data):
    """Create issue links list from fields data with error handling."""
    links_data = fields_data.get("issuelinks", [])
    if not isinstance(links_data, list):
        verbose_print(f"Warning: Invalid issuelinks data format: {type(links_data)}")
        return []

    links = []
    for link_data in links_data:
        if not isinstance(link_data, dict):
            verbose_print(f"Warning: Invalid link data format: {type(link_data)}")
            continue

        link = SimpleNamespace()

        # Handle outward issue
        if "outwardIssue" in link_data:
            outward_data = link_data["outwardIssue"]
            if isinstance(outward_data, dict):
                link.outwardIssue = SimpleNamespace()  # pylint: disable=invalid-name
                link.outwardIssue.key = outward_data.get("key")

        # Handle inward issue
        if "inwardIssue" in link_data:
            inward_data = link_data["inwardIssue"]
            if isinstance(inward_data, dict):
                link.inwardIssue = SimpleNamespace()  # pylint: disable=invalid-name
                link.inwardIssue.key = inward_data.get("key")

        links.append(link)

    return links


def _create_custom_fields(fields_data):
    """Create custom field attributes with error handling."""
    custom_fields = {}

    for field_name, field_value in fields_data.items():
        if not field_name.startswith("customfield_"):
            continue

        try:
            if field_value and isinstance(field_value, dict) and "value" in field_value:
                # Create object with value attribute for custom fields
                custom_field = SimpleNamespace()
                custom_field.value = field_value["value"]
                custom_fields[field_name] = custom_field
            else:
                custom_fields[field_name] = field_value
        except Exception as e:
            verbose_print(f"Warning: Error processing custom field {field_name}: {e}")
            custom_fields[field_name] = None

    return custom_fields


def _create_changelog_object(raw_issue):
    """Create changelog object from raw issue data with error handling."""
    changelog_data = raw_issue.get("changelog", {})
    if not isinstance(changelog_data, dict):
        verbose_print(f"Warning: Invalid changelog data format: {type(changelog_data)}")
        changelog_data = {}

    changelog = SimpleNamespace()
    changelog.histories = []

    histories_data = changelog_data.get("histories", [])
    if not isinstance(histories_data, list):
        verbose_print(f"Warning: Invalid histories data format: {type(histories_data)}")
        return changelog

    for history_data in histories_data:
        if not isinstance(history_data, dict):
            verbose_print(f"Warning: Invalid history data format: {type(history_data)}")
            continue

        history = SimpleNamespace()
        history.created = history_data.get("created")
        history.items = []

        items_data = history_data.get("items", [])
        if not isinstance(items_data, list):
            verbose_print(f"Warning: Invalid history items data format: {type(items_data)}")
            continue

        for item_data in items_data:
            if not isinstance(item_data, dict):
                verbose_print(f"Warning: Invalid history item data format: {type(item_data)}")
                continue

            item = SimpleNamespace()
            item.field = item_data.get("field")
            item.fromString = item_data.get("fromString")  # pylint: disable=invalid-name
            item.toString = item_data.get("toString")  # pylint: disable=invalid-name
            history.items.append(item)

        changelog.histories.append(history)

    return changelog


def convert_raw_issue_to_simple_object(raw_issue):  # pylint: disable=too-many-statements
    """
    Convert raw JSON issue data to simple objects that work with existing functions.

    Args:
        raw_issue (dict): Raw JSON issue data from JIRA API

    Returns:
        SimpleNamespace: Issue object with fields, changelog, etc.

    Raises:
        ValueError: If raw_issue is not a dictionary or missing required fields
    """
    if not isinstance(raw_issue, dict):
        raise ValueError(f"Expected dictionary, got {type(raw_issue)}")

    if "key" not in raw_issue:
        raise ValueError("Issue missing required 'key' field")

    try:
        # Create main issue object
        issue = SimpleNamespace()
        issue.key = raw_issue.get("key")

        # Create fields object
        fields_data = raw_issue.get("fields", {})
        if not isinstance(fields_data, dict):
            verbose_print(f"Warning: Invalid fields data for {issue.key}: {type(fields_data)}")
            fields_data = {}

        issue.fields = SimpleNamespace()

        # Add standard fields using helper functions
        issue.fields.project = _create_project_object(fields_data)
        issue.fields.status = _create_status_object(fields_data)
        issue.fields.priority = _create_priority_object(fields_data)
        issue.fields.assignee = _create_assignee_object(fields_data)
        issue.fields.issuelinks = _create_issue_links(fields_data)
        # Include commonly used primitive fields
        issue.fields.summary = fields_data.get("summary")
        issue.fields.created = fields_data.get("created")
        issue.fields.duedate = fields_data.get("duedate")
        issue.fields.resolutiondate = fields_data.get("resolutiondate")

        # Add custom fields
        custom_fields = _create_custom_fields(fields_data)
        for field_name, field_value in custom_fields.items():
            setattr(issue.fields, field_name, field_value)

        # Create changelog object
        issue.changelog = _create_changelog_object(raw_issue)

        return issue

    except Exception as e:
        issue_key = raw_issue.get("key", "unknown")
        verbose_print(f"Error converting issue {issue_key}: {e}")
        raise ValueError(f"Failed to convert issue {issue_key}: {e}") from e


class SimpleNamespace:
    """Simple object to hold attributes dynamically."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def get_tickets_from_jira(jql_query):
    """
    Retrieve tickets using JIRA REST API v3 /search/jql endpoint.
    Returns converted issue objects compatible with existing business logic.

    This function uses direct HTTP requests to the v3 API with proper error handling,
    retry logic, and pagination support. Includes changelog expansion for status history.
    """
    # Get environment variables
    jira_link = os.environ.get("JIRA_LINK")
    user_email = os.environ.get("USER_EMAIL")
    api_key = os.environ.get("JIRA_API_KEY")

    if not all([jira_link, user_email, api_key]):
        raise ValueError("Missing required environment variables for direct v3 API access")

    # Use the correct v3 /search/jql endpoint (not the deprecated /search endpoint)
    api_search_url = f"{jira_link.rstrip('/')}/rest/api/3/search/jql"

    verbose_print(f"Using direct v3 API endpoint: {api_search_url}")
    verbose_print(f"JQL query: {jql_query}")

    headers = {"Accept": "application/json", "Content-Type": "application/json"}

    all_issues = []
    next_page_token = None
    max_results = 100

    while True:
        params = {
            "jql": jql_query,
            "maxResults": max_results,
            "expand": "changelog",  # Include changelog for cycle time analysis
            "fields": "*all",  # Get all fields
        }

        # Add pagination token if we have one
        if next_page_token:
            params["nextPageToken"] = next_page_token

        # Make request with retry logic (similar to epic_tracking.py)
        for attempt in range(5):
            try:
                response = requests.get(
                    api_search_url, params=params, auth=(user_email, api_key), headers=headers, timeout=30
                )

                verbose_print(f"Response status: {response.status_code}")

                if response.status_code in (429, 500, 502, 503, 504):
                    wait = min(2**attempt, 10)
                    verbose_print(f"Rate limited or server error, waiting {wait}s...")
                    time.sleep(wait)
                    continue

                if response.status_code != 200:
                    print(f"ERROR: Request failed with status {response.status_code}")
                    print(f"URL: {response.url}")
                    print(f"Response: {response.text[:500]}")  # Limit response text

                response.raise_for_status()
                break

            except requests.exceptions.RequestException as e:
                if attempt == 4:  # Last attempt
                    raise
                wait = min(2**attempt, 10)
                verbose_print(f"Request exception: {e}. Retrying in {wait}s...")
                time.sleep(wait)

        # Parse JSON response with error handling
        try:
            data = response.json()
        except ValueError as e:  # JSONDecodeError is a subclass of ValueError
            print("ERROR: Failed to decode JSON response")
            print(f"Response status: {response.status_code}")
            print(f"Response headers: {dict(response.headers)}")
            print(f"Response text (first 500 chars): {response.text[:500]}")
            raise ValueError(f"Invalid JSON response from JIRA API: {e}") from e

        # Validate response structure
        if not isinstance(data, dict):
            print(f"ERROR: Expected JSON object, got {type(data)}")
            print(f"Response data: {data}")
            raise ValueError(f"Unexpected response format: expected JSON object, got {type(data).__name__}")

        issues = data.get("issues", [])
        all_issues.extend(issues)

        verbose_print(f"Retrieved {len(issues)} issues (total so far: {len(all_issues)})")

        # Check if this is the last page using v3 API pagination format
        is_last = data.get("isLast", True)
        next_page_token = data.get("nextPageToken")

        verbose_print(f"Is last page: {is_last}, Next page token: {next_page_token is not None}")

        if is_last or len(issues) == 0:
            verbose_print(f"Breaking pagination loop: is_last={is_last}, issues_count={len(issues)}")
            break

    verbose_print(f"Direct v3 API search completed: {len(all_issues)} total issues found")

    # Convert raw JSON issues to objects compatible with existing business logic
    converted_issues = []
    for raw_issue in all_issues:
        converted_issues.append(convert_raw_issue_to_simple_object(raw_issue))

    verbose_print(f"Converted {len(converted_issues)} raw issues to compatible objects")
    return converted_issues


# pylint: disable=too-many-locals
def get_tickets_from_graphql(start_date, end_date):
    """
    Retrieve tickets using GraphQL instead of JIRA REST API
    """
    # Get GraphQL endpoint from environment
    jira_url = os.environ.get("JIRA_LINK")
    if not jira_url:
        raise ValueError("JIRA_LINK environment variable not set")

    # Use the correct Atlassian Cloud GraphQL endpoint
    graphql_endpoint = f"{jira_url.rstrip('/')}/gateway/api/graphql"

    api_key = os.environ.get("JIRA_API_KEY")
    if not api_key:
        raise ValueError("JIRA_API_KEY environment variable not set")

    custom_field_team = os.environ.get("CUSTOM_FIELD_TEAM")
    if not custom_field_team:
        raise ValueError("CUSTOM_FIELD_TEAM environment variable not set")

    print(f"Using GraphQL endpoint: {graphql_endpoint}")  # Debug print

    # Create the dynamic field name for the team field
    team_field = f"customfield_{custom_field_team}"

    # Setup GraphQL client with proper authentication
    transport = RequestsHTTPTransport(
        url=graphql_endpoint,
        headers={
            "Authorization": f"Basic {api_key}",
            "Content-Type": "application/json",
        },
        verify=True,  # Enable SSL verification
    )

    try:
        client = Client(transport=transport, fetch_schema_from_transport=True)

        # Define GraphQL query
        query = gql(
            f"""
        query GetJiraIssues($startDate: String!, $endDate: String!, $after: String) {{
          issues(
            first: 100,
            after: $after,
            jql: "status changed to Released during ($startDate, $endDate) AND issueType in (Task, Bug, Story, Spike)"
          ) {{
            nodes {{
              key
              fields {{
                status {{
                  name
                }}
                created
                project {{
                  key
                }}
                {team_field} {{
                  value
                }}
                changelog {{
                  histories {{
                    created
                    items {{
                      field
                      fromString
                      toString
                    }}
                  }}
                }}
              }}
            }}
            pageInfo {{
              hasNextPage
              endCursor
            }}
          }}
        }}
        """
        )

        # Execute query with pagination
        all_tickets = []
        has_next_page = True
        cursor = None

        while has_next_page:
            variables = {"startDate": start_date, "endDate": end_date, "after": cursor}

            try:
                result = client.execute(query, variable_values=variables)

                # Process results
                if "issues" in result and "nodes" in result["issues"]:
                    tickets = result["issues"]["nodes"]
                    all_tickets.extend(tickets)

                    # Handle pagination
                    page_info = result["issues"]["pageInfo"]
                    has_next_page = page_info["hasNextPage"]
                    cursor = page_info["endCursor"]
                else:
                    print("Unexpected response format from GraphQL query")
                    break

            except Exception as e:
                print(f"Error executing GraphQL query: {str(e)}")
                break

        return all_tickets

    except Exception as e:
        print(f"Error setting up GraphQL client: {str(e)}")
        raise


def get_team(ticket):
    team_field = None
    if CUSTOM_FIELD_TEAM:
        team_field = getattr(ticket.fields, f"customfield_{CUSTOM_FIELD_TEAM}", None)
    if team_field:
        return team_field.value.strip().lower().capitalize()
    project_key = ticket.fields.project.key.upper()
    default_team = os.getenv(f"TEAM_{project_key}")
    if default_team:
        return default_team.strip().lower().capitalize()

    # Environment variable for project {project_key} not found. Using project key as team
    return project_key.strip().lower().capitalize()


def get_ticket_points(ticket):
    # Using points IS sketcy, since it's a complete completeable, team-owned variable.
    # it CAN make sense to show patterns emerging, and strengthening the picture from other metrics
    # such as ticket count, but it's not a reliable metric on its own.
    story_points = getattr(ticket.fields, f"customfield_{CUSTOM_FIELD_STORYPOINTS}")
    return int(story_points) if story_points else 0


def get_children_for_epic(epic_key: str):
    """Get child issues for an epic (works for company-managed and team-managed).

    Args:
        epic_key (str): The epic key (e.g., 'PROJ-123')

    Returns:
        List of converted issue objects compatible with jira_utils functions
    """
    # We explicitly exclude Epics here and allow any standard child type
    jql = f'issuetype != Epic AND ("Epic Link" = {epic_key} OR parent = {epic_key})'

    verbose_print(f"Fetching children for epic {epic_key}")
    return get_tickets_from_jira(jql)


def parse_jira_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    for date_format in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(value, date_format)
        except ValueError:
            continue
    return None


def month_key_from_jira_datetime(value: str | None) -> str:
    parsed_date = parse_jira_datetime(value)
    if not parsed_date:
        return "unknown"
    return parsed_date.strftime("%Y-%m")


def get_project_key(issue: object) -> str:
    fields = getattr(issue, "fields", None)
    project = getattr(fields, "project", None)
    project_key = getattr(project, "key", None)
    if isinstance(project_key, str) and project_key.strip():
        return project_key.strip().upper()

    issue_key = getattr(issue, "key", "")
    if isinstance(issue_key, str) and "-" in issue_key:
        return issue_key.split("-", 1)[0].strip().upper()
    return "UNKNOWN"


def _get_field_value(field: object) -> str | None:
    value = getattr(field, "value", field)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _format_team_name(value: str) -> str:
    return value.strip().lower().capitalize()


def get_team_or_project_unknown(issue: object) -> str:
    configured_field = os.environ.get("CUSTOM_FIELD_TEAM")
    fields = getattr(issue, "fields", None)
    if configured_field and fields:
        team_field = getattr(fields, f"customfield_{configured_field}", None)
        team = _get_field_value(team_field)
        if team:
            return _format_team_name(team)

    return f"{get_project_key(issue)}/unknown-team"


def extract_status_timestamps(issue):
    # Extract the status change timestamps and normalize them to newest-first.
    # This makes the downstream interpretation deterministic even if the API
    # returns changelog histories in a different order.
    status_timestamps = []
    for history in issue.changelog.histories:
        for item in history.items:
            if item.field == "status":
                verbose_print(f"{issue.key} processing status change: {item.toString}, timestamp: {history.created}")
                status_timestamps.append(
                    {
                        "status": item.toString,
                        "timestamp": datetime.strptime(history.created, "%Y-%m-%dT%H:%M:%S.%f%z"),
                    }
                )
    status_timestamps.sort(key=lambda entry: entry["timestamp"], reverse=True)
    return status_timestamps


def get_status_transitions_chronological(issue: object) -> list[StatusTransition]:
    status_timestamps = extract_status_timestamps(issue)
    transitions = []
    for entry in reversed(status_timestamps):
        status = entry["status"]
        timestamp = entry["timestamp"]
        if isinstance(status, str) and isinstance(timestamp, datetime):
            transitions.append(StatusTransition(status=status, timestamp=timestamp))
    return transitions


def get_issue_created_month_key(issue: object) -> str:
    fields = getattr(issue, "fields", None)
    created = getattr(fields, "created", None)
    return month_key_from_jira_datetime(created)


def is_month_key_in_date_range(month_key: str, start_date: str, end_date: str) -> bool:
    try:
        datetime.strptime(month_key, "%Y-%m")
    except ValueError:
        return False
    return start_date[:7] <= month_key <= end_date[:7]


def calculate_total_time_in_status(
    issue: object,
    status_name: str,
    seconds_between: Callable[[datetime, datetime], float],
) -> TimeInStatusResult:
    issue_id = getattr(issue, "key", "unknown")
    target_status = status_name.strip().casefold()
    current_start = None
    saw_status = False
    completed_intervals = 0
    total_seconds = 0.0
    last_exit_timestamp = None

    for transition in get_status_transitions_chronological(issue):
        if transition.status.strip().casefold() == target_status:
            saw_status = True
            current_start = transition.timestamp
            continue

        if current_start is None:
            continue

        total_seconds += seconds_between(current_start, transition.timestamp)
        completed_intervals += 1
        last_exit_timestamp = transition.timestamp
        current_start = None

    return TimeInStatusResult(
        issue_id=issue_id,
        saw_status=saw_status,
        completed_intervals=completed_intervals,
        total_seconds=total_seconds,
        last_exit_timestamp=last_exit_timestamp,
        open_start_timestamp=current_start,
    )


def interpret_status_timestamps(status_timestamps):
    # Interpret the status change timestamps to determine the status timestamps that is of value
    # code review --> the FIRST code review date
    # completion   --> the MOST RECENT occurrence among configured completion statuses
    code_review_statuses = get_code_review_statuses()
    extracted_statuses = {
        JiraStatus.CODE_REVIEW.value: None,
        JiraStatus.RELEASED.value: None,
        JiraStatus.DONE.value: None,
    }

    # status_timestamps is normalized to newest-first; reverse it to inspect
    # the earliest transitions first and capture the first code review entry.
    for entry in reversed(status_timestamps):
        status = entry["status"]
        timestamp = entry["timestamp"]
        if status.lower() in code_review_statuses and not extracted_statuses[JiraStatus.CODE_REVIEW.value]:
            extracted_statuses[JiraStatus.CODE_REVIEW.value] = timestamp
            # we only check for code review for now. We might want to change this later.
            break

    # Determine the MOST RECENT completion status based on configuration
    completion_statuses = get_completion_statuses()
    most_recent_completion_timestamp = None
    most_recent_completion_name = None

    # status_timestamps is normalized to newest-first; iterate forward and stop
    # on the first match to capture the most recent completion.
    for entry in status_timestamps:
        status = entry["status"].lower()
        timestamp = entry["timestamp"]
        if status in completion_statuses:
            most_recent_completion_timestamp = timestamp
            most_recent_completion_name = status
            break  # Break on first match which is the most recent

    # For compatibility, set both RELEASED and DONE to the most recent completion timestamp
    if most_recent_completion_timestamp:
        extracted_statuses[JiraStatus.RELEASED.value] = most_recent_completion_timestamp
        extracted_statuses[JiraStatus.DONE.value] = most_recent_completion_timestamp
        verbose_print(
            f"Most recent completion status detected: '{most_recent_completion_name}' at {most_recent_completion_timestamp}"
        )

    return extracted_statuses
