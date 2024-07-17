import os
import json
from jira import JIRA
#from jira_metrics.utilities.jira_query import create_jql_query

def setup_jira_instance():
    jira_api_key = os.getenv("JIRA_API_KEY")
    jira_link = os.getenv("JIRA_LINK")
    user_email = os.getenv("USER_EMAIL")

    if not all([jira_api_key, jira_link, user_email]):
        raise EnvironmentError("Missing one or more environment variables: JIRA_API_KEY, JIRA_LINK, USER_EMAIL")

    options = {'server': jira_link}
    jira = JIRA(options, basic_auth=(user_email, jira_api_key))
    return jira

def read_queries_from_file(file_path):
    with open(file_path, 'r') as file:
        queries = json.load(file)
    return queries

def fetch_tickets(jira, query):
    issues = jira.search_issues(query, maxResults=-1)
    return issues

def main():
    jira = setup_jira_instance()
    queries = read_queries_from_file('queries/queries.json')

    for query in queries:
        issues = fetch_tickets(jira, query['jql'])
        print(f"Found {len(issues)} issues for query: {query['description']}")

if __name__ == "__main__":
    main()