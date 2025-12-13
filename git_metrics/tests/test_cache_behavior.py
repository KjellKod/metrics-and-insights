#!/usr/bin/env python3
"""
Tests for PR cache invalidation behavior in ci_pr_performance_metrics.py.

We avoid network calls by patching execute_graphql_query and run in a
temporary working directory so the cache file does not interfere with
other tests or local runs.
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

# Add git_metrics directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from ci_pr_performance_metrics import get_pull_requests  # noqa: E402


class TestPRCacheInvalidation(unittest.TestCase):
    def setUp(self):
        # Isolated temp working directory per test
        self._cwd = os.getcwd()
        self._tmpdir = tempfile.TemporaryDirectory()
        os.chdir(self._tmpdir.name)

        # Minimal required env vars for the function under test
        os.environ["GITHUB_METRIC_OWNER_OR_ORGANIZATION"] = "test-owner"
        os.environ["GITHUB_METRIC_REPO"] = "test-repo"

        # Ensure no force-fresh by default
        os.environ.pop("PR_CACHE_FORCE_FRESH", None)
        os.environ["PR_CACHE_TTL_HOURS"] = "8"

    def tearDown(self):
        # Cleanup and restore cwd
        os.chdir(self._cwd)
        self._tmpdir.cleanup()
        os.environ.pop("PR_CACHE_TTL_HOURS", None)
        os.environ.pop("PR_CACHE_FORCE_FRESH", None)
        os.environ.pop("GITHUB_METRIC_OWNER_OR_ORGANIZATION", None)
        os.environ.pop("GITHUB_METRIC_REPO", None)

    @patch("ci_pr_performance_metrics.execute_graphql_query")
    def test_cache_expired_is_removed(self, mock_query):
        """Expired cache (older than TTL) should be ignored and deleted."""
        # Create an expired cache file
        expired_ts = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        with open("pr_cache.json", "w", encoding="utf-8") as f:
            json.dump({"prs": ["dummy"], "cursor": "abc", "timestamp": expired_ts}, f)

        # Return a minimal structure with no nodes to exit quickly
        mock_query.return_value = {
            "data": {
                "repository": {"pullRequests": {"nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}
            }
        }

        # Act
        get_pull_requests("2024-01-01T00:00:00Z")

        # Assert the old file was removed (may or may not be recreated depending on flow)
        self.assertFalse(os.path.exists("pr_cache.json"), "Expired cache should be deleted")

    @patch("ci_pr_performance_metrics.execute_graphql_query")
    def test_cache_force_fresh_deletes(self, mock_query):
        """PR_CACHE_FORCE_FRESH=1 should ignore and delete cache regardless of age."""
        # Create a fresh cache file
        fresh_ts = datetime.now(timezone.utc).isoformat()
        with open("pr_cache.json", "w", encoding="utf-8") as f:
            json.dump({"prs": ["dummy"], "cursor": "abc", "timestamp": fresh_ts}, f)

        os.environ["PR_CACHE_FORCE_FRESH"] = "1"

        mock_query.return_value = {
            "data": {
                "repository": {"pullRequests": {"nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}
            }
        }

        # Act
        get_pull_requests("2024-01-01T00:00:00Z")

        # Assert the file was removed
        self.assertFalse(os.path.exists("pr_cache.json"), "Cache should be deleted when force fresh is set")


if __name__ == "__main__":
    unittest.main()
