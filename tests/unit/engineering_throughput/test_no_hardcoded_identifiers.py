from __future__ import annotations

from pathlib import Path


DENY_LIST = [
    "2025 vs 2026",
    "onfleet",
    "Spork",
    "Panda",
    "Mint",
    "Blackwidow",
    "rodolfo",
    "Gonzalo",
    "Nastassy",
]


def test_committed_modules_do_not_leak_hardcoded_identifiers() -> None:
    paths = sorted(Path("engineering_throughput").glob("*.py"))
    paths.extend(sorted(Path("git_metrics").glob("throughput_*.py")))
    paths.append(Path("jira_metrics/throughput_summary.py"))

    for path in paths:
        text = path.read_text(encoding="utf-8")
        for token in DENY_LIST:
            assert token not in text, f"found leaked token {token!r} in {path}"
