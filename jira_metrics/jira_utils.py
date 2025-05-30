import os
from enum import Enum
from datetime import datetime
import argparse
from dotenv import load_dotenv
from jira import JIRA
from gql import gql, Client
from gql.transport.requests import RequestsHTTPTransport

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

    options = {"server": link, "verify": True}  # Ensure SSL verification is enabled

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


def get_tickets_from_jira(jql_query):
    # Get the Jira instance
    jira = get_jira_instance()
    print(f"jql: '{jql_query}'")

    max_results = 100
    start_at = 0
    total_tickets = []

    while True:
        tickets = jira.search_issues(jql_query, startAt=start_at, maxResults=max_results, expand="changelog")
        if len(tickets) == 0:
            break
        print(f"Received {len(tickets)} tickets")
        total_tickets.extend(tickets)
        start_at += max_results
        if len(tickets) < max_results:
            break
    return total_tickets


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
