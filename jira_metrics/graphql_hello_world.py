"""
Jira GraphQL API Connection Template
A minimal example to verify Jira connectivity and authentication.
"""

import os
import sys
import logging
import base64
from dotenv import load_dotenv
from gql import gql, Client
from gql.transport.requests import RequestsHTTPTransport

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def verify_jira_connection():
    """Verify Jira GraphQL API connection and print user information."""

    # Load environment variables
    load_dotenv()

    # Required environment variables
    jira_url = os.getenv("JIRA_LINK")
    api_key = os.getenv("JIRA_API_KEY")
    user_email = os.getenv("USER_EMAIL")

    if not all([jira_url, api_key, user_email]):
        logger.error("Missing required environment variables:")
        if not jira_url:
            logger.error("- JIRA_LINK")
        if not api_key:
            logger.error("- JIRA_API_KEY")
        if not user_email:
            logger.error("- USER_EMAIL")
        return False

    try:
        # Setup GraphQL client
        credentials = base64.b64encode(f"{user_email}:{api_key}".encode()).decode()
        transport = RequestsHTTPTransport(
            url=f"{jira_url.rstrip('/')}/gateway/api/graphql",
            headers={"Authorization": f"Basic {credentials}", "Content-Type": "application/json"},
        )

        client = Client(transport=transport, fetch_schema_from_transport=True)

        # Query user information
        query = gql(
            """
            query GetCurrentUser {
                me {
                    user {
                        ... on AtlassianAccountUser {
                            email
                            accountId
                        }
                    }
                }
            }
        """
        )

        result = client.execute(query)

        # Print user information
        user_data = result.get("me", {}).get("user", {})
        if user_data:
            logger.info("\nAuthenticated User Information:")
            logger.info("Email: %s", user_data.get("email"))
            logger.info("Account ID: %s", user_data.get("accountId"))
            return True

        logger.error("Failed to get user information")
        return False

    except Exception as e:
        logger.error("Connection failed: %s", str(e))
        return False


def main():
    logger.info("Testing Jira GraphQL API connection...")
    if verify_jira_connection():
        logger.info("\nConnection test successful! ✨")
        sys.exit(0)
    else:
        logger.error("\nConnection test failed! 💥")
        sys.exit(1)


if __name__ == "__main__":
    main()
