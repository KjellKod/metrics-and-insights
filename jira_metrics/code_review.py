import os
import sys
import logging
from datetime import datetime
import base64
from typing import Dict, Optional

import requests
from gql import gql, Client
from gql.transport.requests import RequestsHTTPTransport
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging first
logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)


def validate_env_variables() -> Dict[str, str]:
    """Validate required environment variables and return their values."""
    required_vars = {
        "JIRA_API_KEY": "Jira API token",
        "USER_EMAIL": "User email",
        "JIRA_LINK": "Jira instance URL",
        "JIRA_PROJECTS": "Comma-separated list of Jira projects",
    }

    missing_vars = []
    env_values = {}

    for var, description in required_vars.items():
        value = os.environ.get(var)
        if not value:
            missing_vars.append(f"{var} ({description})")
        env_values[var] = value

    if missing_vars:
        logger.error("Missing required environment variables:\n%s", "\n".join(f"- {var}" for var in missing_vars))
        raise ValueError("Missing required environment variables")

    return env_values


def setup_graphql_client() -> Client:
    """Setup GraphQL client with authentication."""
    env_vars = validate_env_variables()

    # Create base64 encoded credentials
    credentials = base64.b64encode(f"{env_vars['USER_EMAIL']}:{env_vars['JIRA_API_KEY']}".encode()).decode()

    # Setup the GraphQL endpoint
    jira_url = env_vars["JIRA_LINK"].rstrip("/")
    graphql_endpoint = f"{jira_url}/gateway/api/graphql"

    logger.info("Connecting to GraphQL endpoint: %s", graphql_endpoint)
    logger.info("Using credentials for user: %s", env_vars["USER_EMAIL"])

    transport = RequestsHTTPTransport(
        url=graphql_endpoint,
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
            "X-ExperimentalApi": "opt-in",  # Add this header as mentioned in docs
        },
        verify=True,
    )

    return Client(transport=transport, fetch_schema_from_transport=True)


def execute_hello_world_query() -> Optional[Dict]:
    """Execute a simple GraphQL query to verify Jira connectivity."""
    try:
        client = setup_graphql_client()
        jira_url = os.environ.get("JIRA_LINK")
        expected_email = os.environ.get("USER_EMAIL")

        if not jira_url or not expected_email:
            raise ValueError("Missing required environment variables: JIRA_LINK or USER_EMAIL")

        # Extract hostname from JIRA_LINK
        hostname = jira_url.replace("https://", "").replace("http://", "").rstrip("/")

        # First query to get cloudId (this worked)
        cloud_query = gql(
            """
            query GetCloudId($hostNames: [String!]!) {
                tenantContexts(hostNames: $hostNames) {
                    cloudId
                }
            }
        """
        )

        variables = {"hostNames": [hostname]}

        logger.info("Getting cloud ID...")
        result = client.execute(cloud_query, variable_values=variables)

        if result.get("tenantContexts"):
            logger.info("Successfully connected to Jira GraphQL API!")
            return result
        else:
            logger.error("Could not get cloud ID")
            return None

    except Exception as e:
        logger.error("Error executing GraphQL query: %s", str(e))
        if hasattr(e, "response"):
            logger.error("Response status code: %s", e.response.status_code)
            logger.error("Response body: %s", e.response.text)
        return None


def main():
    try:
        logger.info("Testing Jira GraphQL API connection...")
        result = execute_hello_world_query()

        if result and "tenantContexts" in result:
            logger.info("Successfully connected to Jira GraphQL API!")
            logger.info("Cloud ID: %s", result["tenantContexts"])
        else:
            logger.error("Failed to connect to Jira GraphQL API")
            sys.exit(1)

    except Exception as e:
        logger.error("An error occurred: %s", str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
