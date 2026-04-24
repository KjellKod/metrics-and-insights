from __future__ import annotations

import os
from pathlib import Path


def _blocked_identifier_tokens() -> tuple[str, ...]:
    raw = os.environ.get("THROUGHPUT_BLOCKED_IDENTIFIER_TOKENS", "")
    return tuple(token.strip() for token in raw.split(",") if token.strip())


def test_committed_modules_do_not_leak_hardcoded_identifiers() -> None:
    paths = sorted(Path("engineering_throughput").glob("*.py"))
    paths.extend(sorted(Path("git_metrics").glob("throughput_*.py")))
    paths.append(Path("jira_metrics/throughput_summary.py"))
    blocked_tokens = _blocked_identifier_tokens()

    for path in paths:
        text = path.read_text(encoding="utf-8")
        for token in blocked_tokens:
            assert token not in text, f"found leaked token {token!r} in {path}"
