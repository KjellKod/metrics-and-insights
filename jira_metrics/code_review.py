import os
import sys
import logging
import base64
from typing import Optional, Dict

from gql import gql, Client
from gql.transport.requests import RequestsHTTPTransport
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)


def validate_env_variables() -> Dict[str, str]:
    """Validate required environment variables."""
    required_vars = {
        "USER_EMAIL": "User email for authentication",
        "JIRA_API_KEY": "Jira API token",
        "JIRA_LINK": "Jira instance URL",
    }

    env_values = {}
    missing_vars = []

    for var, description in required_vars.items():
        value = os.environ.get(var)
        if not value:
            missing_vars.append(f"{var} ({description})")
        env_values[var] = value

    if missing_vars:
        raise ValueError(f"Missing required environment variables:\n{chr(10).join(missing_vars)}")

    return env_values


def setup_graphql_client() -> Client:
    """Setup GraphQL client with authentication."""
    env_vars = validate_env_variables()

    # Create base64 encoded credentials
    credentials = base64.b64encode(f"{env_vars['USER_EMAIL']}:{env_vars['JIRA_API_KEY']}".encode()).decode()

    # Setup the GraphQL endpoint
    jira_url = env_vars["JIRA_LINK"].rstrip("/")
    graphql_endpoint = f"{jira_url}/gateway/api/graphql"

    transport = RequestsHTTPTransport(
        url=graphql_endpoint,
        headers={"Authorization": f"Basic {credentials}", "Content-Type": "application/json"},
        verify=True,
    )

    return Client(transport=transport, fetch_schema_from_transport=True)


def verify_user() -> Optional[Dict]:
    """Verify connection and user email match."""
    try:
        client = setup_graphql_client()
        expected_email = os.environ.get("USER_EMAIL")

        # Query to verify user's email - simplified
        query = gql(
            """
            query GetCurrentUser {
                me {
                    user {
                        ... on AtlassianAccountUser {
                            email
                        }
                    }
                }
            }
        """
        )

        result = client.execute(query)
        current_email = result.get("me", {}).get("user", {}).get("email")

        if current_email == expected_email:
            logger.info("Successfully authenticated with correct user email: %s", current_email)
            return result
        else:
            logger.error("Email mismatch: authenticated as %s but expected %s", current_email, expected_email)
            return None

    except Exception as e:
        logger.error("Error executing GraphQL query: %s", str(e))
        return None


def main():
    try:
        logger.info("Testing Jira GraphQL API connection...")
        result = verify_user()

        if result:
            logger.info("Connection test successful!")
            logger.info("You can now build your Jira GraphQL queries.")
        else:
            logger.error("Failed to verify Jira connection")
            sys.exit(1)

    except Exception as e:
        logger.error("An error occurred: %s", str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
