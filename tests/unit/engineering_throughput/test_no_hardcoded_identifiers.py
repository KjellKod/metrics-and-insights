from __future__ import annotations

from pathlib import Path

from tests.unit.engineering_throughput.identifier_tokens import BLOCKED_IDENTIFIER_TOKENS


def test_committed_modules_do_not_leak_hardcoded_identifiers() -> None:
    paths = sorted(Path("engineering_throughput").glob("*.py"))
    paths.extend(sorted(Path("git_metrics").glob("throughput_*.py")))
    paths.append(Path("jira_metrics/throughput_summary.py"))

    for path in paths:
        text = path.read_text(encoding="utf-8")
        for token in BLOCKED_IDENTIFIER_TOKENS:
            assert token not in text, f"found leaked token {token!r} in {path}"
