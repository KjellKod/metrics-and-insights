import csv
import os
import sys
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
# pylint: disable=wrong-import-position,import-error
import bug_health
from jira_utils import SimpleNamespace

EXAMPLE_TEAM = "Example team"


def make_history(created, to_status):
    item = SimpleNamespace()
    item.field = "status"
    item.fromString = "In Progress"
    item.toString = to_status
    history = SimpleNamespace()
    history.created = created
    history.items = [item]
    return history


def make_ticket(
    key,
    project="BUG",
    team=EXAMPLE_TEAM,
    created="2024-01-01T00:00:00.000+0000",
    status="Open",
    bug_priority=None,
    jira_priority=None,
    due_date=None,
    resolutiondate=None,
    histories=None,
):
    ticket = SimpleNamespace()
    ticket.key = key
    ticket.fields = SimpleNamespace()
    ticket.fields.project = SimpleNamespace()
    ticket.fields.project.key = project
    ticket.fields.status = SimpleNamespace()
    ticket.fields.status.name = status
    ticket.fields.summary = f"{key} summary"
    ticket.fields.created = created
    ticket.fields.duedate = due_date
    ticket.fields.resolutiondate = resolutiondate
    ticket.fields.priority = None
    if jira_priority:
        ticket.fields.priority = SimpleNamespace()
        ticket.fields.priority.name = jira_priority
    if bug_priority is not None:
        field = SimpleNamespace()
        field.value = bug_priority
        ticket.fields.customfield_999 = field
    team_field = SimpleNamespace()
    team_field.value = team
    ticket.fields.customfield_100 = team_field
    ticket.changelog = SimpleNamespace()
    ticket.changelog.histories = histories or []
    return ticket


class TestBugHealthJql(unittest.TestCase):
    @patch("bug_health.get_completion_statuses", return_value=["released", "done", "to release"])
    def test_build_jql_queries_with_projects_and_configured_statuses(self, _mock_statuses):
        queries = bug_health.build_jql_queries(date(2024, 1, 1), date(2024, 1, 31), ["ABC", "DEF"])

        self.assertIn("project IN ('ABC', 'DEF')", queries["created"])
        self.assertIn("created >= '2024-01-01'", queries["created"])
        self.assertIn("created <= '2024-01-31'", queries["created"])
        self.assertIn('status CHANGED TO ("Released", "Done", "To Release")', queries["closed_workflow"])
        self.assertIn("DURING ('2024-01-01', '2024-01-31')", queries["closed_workflow"])
        self.assertIn("resolved >= '2024-01-01'", queries["closed_resolved"])
        self.assertIn("status WAS NOT IN", queries["backlog"])
        self.assertIn("ON '2024-01-31'", queries["backlog"])

    @patch("bug_health.get_completion_statuses", return_value=["released"])
    def test_build_jql_queries_without_projects_for_all_projects(self, _mock_statuses):
        queries = bug_health.build_jql_queries(date(2024, 1, 1), date(2024, 1, 31), None)

        self.assertNotIn("project IN", queries["created"])
        self.assertTrue(queries["created"].startswith("issuetype = Bug"))


class TestBugHealthPriorityAndSla(unittest.TestCase):
    @patch.dict(os.environ, {"CUSTOM_FIELD_BUG_PRIORITY": "999"}, clear=False)
    def test_bug_priority_custom_field_wins_over_jira_priority(self):
        ticket = make_ticket("BUG-1", bug_priority="P1 Major Incident", jira_priority="P3 Minor Impact")

        priority, source = bug_health.get_bug_priority(ticket)

        self.assertEqual(priority, "P1 Major Incident")
        self.assertEqual(source, "bug_priority")
        self.assertEqual(bug_health.normalize_priority(priority), "P1")

    @patch.dict(os.environ, {"CUSTOM_FIELD_BUG_PRIORITY": "999"}, clear=False)
    def test_jira_priority_is_fallback(self):
        ticket = make_ticket("BUG-1", jira_priority="P2 Moderate Issue")

        priority, source = bug_health.get_bug_priority(ticket)

        self.assertEqual(priority, "P2 Moderate Issue")
        self.assertEqual(source, "jira_priority")
        self.assertEqual(bug_health.normalize_priority(priority), "P2")

    @patch.dict(os.environ, {"CUSTOM_FIELD_BUG_PRIORITY": "999"}, clear=False)
    def test_unset_priority_is_reported(self):
        ticket = make_ticket("BUG-1")

        priority, source = bug_health.get_bug_priority(ticket)

        self.assertEqual(priority, "Unset")
        self.assertEqual(source, "unset")

    def test_parse_sla_days_uses_default_and_env_override(self):
        self.assertEqual(bug_health.parse_sla_days("")["P2"], 10)
        self.assertEqual(bug_health.parse_sla_days("P1:2,P4:30"), {"P1": 2, "P4": 30})

    @patch("bug_health.get_completion_statuses", return_value=["released", "done"])
    def test_completion_date_uses_earliest_status_or_resolutiondate(self, _mock_statuses):
        ticket = make_ticket(
            "BUG-1",
            resolutiondate="2024-01-08T00:00:00.000+0000",
            histories=[make_history("2024-01-10T00:00:00.000+0000", "Released")],
        )

        completion_date = bug_health.extract_completion_date(ticket)

        self.assertEqual(completion_date.date(), date(2024, 1, 8))


class TestBugHealthAggregation(unittest.TestCase):
    @patch.dict(os.environ, {"CUSTOM_FIELD_BUG_PRIORITY": "999", "CUSTOM_FIELD_TEAM": "100"}, clear=False)
    @patch("bug_health.get_completion_statuses", return_value=["released"])
    @patch("bug_health.get_team", return_value=EXAMPLE_TEAM)
    @patch("bug_health.get_tickets_from_jira")
    def test_generate_report_dedupes_and_aggregates_company_and_team(
        self, mock_get_tickets, _mock_get_team, _mock_statuses
    ):
        created_ticket = make_ticket(
            "BUG-1",
            team=EXAMPLE_TEAM,
            bug_priority="P2 Moderate Issue",
            due_date="2024-01-20",
            histories=[make_history("2024-01-05T00:00:00.000+0000", "Released")],
        )
        backlog_ticket = make_ticket(
            "BUG-2",
            team=EXAMPLE_TEAM,
            created="2024-01-03T00:00:00.000+0000",
            bug_priority=None,
        )
        mock_get_tickets.side_effect = [
            [created_ticket],
            [created_ticket],
            [created_ticket],
            [backlog_ticket],
        ]

        summaries, details = bug_health.generate_bug_health_report(date(2024, 1, 1), date(2024, 1, 31), ["BUG"])

        self.assertEqual(len(details), 2)
        company_all = next(
            row
            for row in summaries
            if row["period"] == "2024-01"
            and row["scope_type"] == "company"
            and row["scope"] == "all"
            and row["priority"] == "all"
        )
        self.assertEqual(company_all["created_count"], 1)
        self.assertEqual(company_all["closed_count"], 1)
        self.assertEqual(company_all["net_change"], 0)
        self.assertEqual(company_all["open_backlog_count"], 1)
        self.assertEqual(company_all["missing_priority_count"], 1)
        self.assertEqual(company_all["missing_due_date_count"], 1)
        self.assertEqual(company_all["median_days_to_close"], 4)
        self.assertEqual(company_all["p85_days_to_close"], 4)

        team_all = next(
            row
            for row in summaries
            if row["scope_type"] == "team" and row["scope"] == EXAMPLE_TEAM and row["priority"] == "all"
        )
        self.assertEqual(team_all["created_count"], 1)
        self.assertEqual(team_all["open_backlog_count"], 1)

    @patch.dict(os.environ, {"CUSTOM_FIELD_BUG_PRIORITY": "999", "CUSTOM_FIELD_TEAM": "100"}, clear=False)
    @patch("bug_health.get_completion_statuses", return_value=["released"])
    @patch("bug_health.get_team", return_value=EXAMPLE_TEAM)
    def test_ticket_detail_marks_open_sla_breach_against_period_end(self, _mock_get_team, _mock_statuses):
        ticket = make_ticket(
            "BUG-1",
            created="2024-01-01T00:00:00.000+0000",
            bug_priority="P1 Major Incident",
        )
        period = {"label": "2024-01", "start": date(2024, 1, 1), "end": date(2024, 1, 31)}
        included = {"created": {"BUG-1"}, "closed": set(), "backlog": {"BUG-1"}}

        detail = bug_health.ticket_to_detail(ticket, period, included, {"P1": 1})

        self.assertEqual(detail["days_open_or_to_close"], 30)
        self.assertTrue(detail["sla_breached"])

    @patch.dict(os.environ, {"CUSTOM_FIELD_BUG_PRIORITY": "999", "CUSTOM_FIELD_TEAM": "100"}, clear=False)
    @patch("bug_health.get_completion_statuses", return_value=["released"])
    @patch("bug_health.get_team", return_value=EXAMPLE_TEAM)
    def test_backlog_ticket_with_future_completion_ages_to_period_end(self, _mock_get_team, _mock_statuses):
        ticket = make_ticket(
            "BUG-1",
            created="2024-01-01T00:00:00.000+0000",
            bug_priority="P2 Moderate Issue",
            resolutiondate="2024-02-15T00:00:00.000+0000",
        )
        period = {"label": "2024-01", "start": date(2024, 1, 1), "end": date(2024, 1, 31)}
        included = {"created": set(), "closed": set(), "backlog": {"BUG-1"}}

        detail = bug_health.ticket_to_detail(ticket, period, included, {"P2": 10})

        self.assertEqual(detail["completion_date"], "2024-02-15")
        self.assertEqual(detail["days_open_or_to_close"], 30)
        self.assertTrue(detail["sla_breached"])


class TestBugHealthCsv(unittest.TestCase):
    def test_write_csv(self):
        rows = [
            {
                "period": "2024-01",
                "scope_type": "company",
                "scope": "all",
                "priority": "all",
                "created_count": 1,
                "closed_count": 1,
                "net_change": 0,
                "open_backlog_count": 0,
                "sla_breached_count": 0,
                "sla_breach_rate": 0,
                "missing_priority_count": 0,
                "missing_due_date_count": 0,
                "median_days_to_close": 4,
                "p85_days_to_close": 4,
            }
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = os.path.join(tmpdir, "summary.csv")
            bug_health.write_csv(rows, bug_health.SUMMARY_FIELDNAMES, output_file)

            with open(output_file, newline="", encoding="utf-8") as csvfile:
                csv_rows = list(csv.DictReader(csvfile))
        self.assertEqual(csv_rows[0]["period"], "2024-01")
        self.assertEqual(csv_rows[0]["created_count"], "1")


class TestBugHealthConsoleSummary(unittest.TestCase):
    def test_render_console_summary_empty(self):
        rendered = bug_health.render_console_summary([], [])

        self.assertIn("No matching bugs found", rendered)

    def test_render_console_summary_includes_key_insights_without_details_dump(self):
        summaries = [
            {
                "period": "2024-01",
                "scope_type": "company",
                "scope": "all",
                "priority": "all",
                "created_count": 5,
                "closed_count": 3,
                "net_change": 2,
                "open_backlog_count": 4,
                "sla_breached_count": 1,
                "sla_breach_rate": 0.25,
                "missing_priority_count": 1,
                "missing_due_date_count": 2,
                "median_days_to_close": 4,
                "p85_days_to_close": 8,
            },
            {
                "period": "2024-02",
                "scope_type": "company",
                "scope": "all",
                "priority": "all",
                "created_count": 2,
                "closed_count": 5,
                "net_change": -3,
                "open_backlog_count": 1,
                "sla_breached_count": 0,
                "sla_breach_rate": 0,
                "missing_priority_count": 0,
                "missing_due_date_count": 1,
                "median_days_to_close": 3,
                "p85_days_to_close": 6,
            },
            {
                "period": "2024-02",
                "scope_type": "team",
                "scope": EXAMPLE_TEAM,
                "priority": "all",
                "created_count": 2,
                "closed_count": 1,
                "net_change": 1,
                "open_backlog_count": 3,
                "sla_breached_count": 2,
                "sla_breach_rate": 0.5,
                "missing_priority_count": 0,
                "missing_due_date_count": 0,
                "median_days_to_close": 3,
                "p85_days_to_close": 6,
            },
        ]
        details = [
            {"ticket_key": "BUG-1"},
            {"ticket_key": "BUG-2"},
            {"ticket_key": "BUG-1"},
        ]

        rendered = bug_health.render_console_summary(summaries, details)

        self.assertIn("Range: 2024-01 to 2024-02; unique bugs seen: 2", rendered)
        self.assertIn("Flow: created 7, closed 8, net -1", rendered)
        self.assertIn("Latest period 2024-02: created 2, closed 5, net -3, backlog 1", rendered)
        self.assertIn("SLA/data quality: breached 0 (0.0%), missing priority 0, missing due date 1", rendered)
        self.assertIn(f"{EXAMPLE_TEAM}: backlog 3, net +1, SLA breached 2", rendered)
