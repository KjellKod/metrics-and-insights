import os
from enum import Enum
from datetime import datetime
import argparse
from dotenv import load_dotenv
from jira import JIRA

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
    Create the jira instance
    An easy way to set up your environment variables is through your .zshrc or .bashrc file
    export USER_EMAIL="your_email@example.com"
    export JIRA_API_KEY="your_jira_api_key"
    export JIRA_LINK="https://your_jira_instance.atlassian.net"
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

    user = os.environ.get("USER_EMAIL")
    api_key = os.environ.get("JIRA_API_KEY")
    link = os.environ.get("JIRA_LINK")
    options = {
        "server": link,
    }
    jira = JIRA(options=options, basic_auth=(user, api_key))
    return jira


def get_tickets_from_jira(jql_query):
    # Get the Jira instance
    jira = get_jira_instance()
    print(f"jql: {jql_query}")

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
    # Using points IS sketcy, since it's a complete changeable, team-owned variable.
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
        elif status.lower() == "done" and not extracted_statuses[JiraStatus.DONE.value]:
            extracted_statuses[JiraStatus.DONE.value] = timestamp
            break

    return extracted_statuses
