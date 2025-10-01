import os
import time
from enum import Enum
from datetime import datetime
import argparse
from dotenv import load_dotenv
from jira import JIRA
from gql import gql, Client
from gql.transport.requests import RequestsHTTPTransport
import requests

load_dotenv()

# Access the custom field IDs
CUSTOM_FIELD_TEAM = os.getenv("CUSTOM_FIELD_TEAM")
CUSTOM_FIELD_WORK_TYPE = os.getenv("CUSTOM_FIELD_WORK_TYPE")
CUSTOM_FIELD_STORYPOINTS = os.getenv("CUSTOM_FIELD_STORYPOINTS")

# Global variable for verbosity
VERBOSE = False


def verbose_print(message):
    if VERBOSE:
        print(message)


class JiraStatus(Enum):
    CODE_REVIEW = "code review"
    RELEASED = "released"
    DONE = "done"


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
    return parser.parse_args()


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
        issue.fields.assignee = _create_assignee_object(fields_data)
        issue.fields.issuelinks = _create_issue_links(fields_data)

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
    team_field = getattr(ticket.fields, f"customfield_{CUSTOM_FIELD_TEAM}")
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


def extract_status_timestamps(issue):
    # Extract the status change timestamps. Most recent first.
    # To see the oldest first, reverse the order of histories (reverse(extract_status_timestamps(issue)))
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
    return status_timestamps


def interpret_status_timestamps(status_timestamps):
    # Interpret the status change timestamps to determine the status timestamps that is of value
    # example: released --> the LAST release date, code review --> the FIRST code review date
    code_review_statuses = {
        "code review",
        "in code review",
        "to review",
        "to code review",
        "in review",
        "in design review",
    }
    extracted_statuses = {
        JiraStatus.CODE_REVIEW.value: None,
        JiraStatus.RELEASED.value: None,
        JiraStatus.DONE.value: None,
    }

    # we look at in chronological order and the FIRST time we go into code-review
    for entry in reversed(status_timestamps):
        status = entry["status"]
        timestamp = entry["timestamp"]
        if status.lower() in code_review_statuses and not extracted_statuses[JiraStatus.CODE_REVIEW.value]:
            extracted_statuses[JiraStatus.CODE_REVIEW.value] = timestamp
            # we might want to change this later, but for now we only check for code review
            break

    # look at the histories in reverse-chronological order to find the LAST time it was released.
    for entry in status_timestamps:
        status = entry["status"]
        timestamp = entry["timestamp"]
        if status.lower() == "released" and not extracted_statuses[JiraStatus.RELEASED.value]:
            extracted_statuses[JiraStatus.RELEASED.value] = timestamp
            break
        if status.lower() == "done" and not extracted_statuses[JiraStatus.DONE.value]:
            extracted_statuses[JiraStatus.DONE.value] = timestamp
            break

    return extracted_statuses
