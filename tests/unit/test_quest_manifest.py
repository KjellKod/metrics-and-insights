from __future__ import annotations

import fnmatch
import re
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _manifest_entries() -> set[str]:
    manifest_path = _repo_root() / ".quest-manifest"
    entries: set[str] = set()
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and not stripped.startswith("["):
            entries.add(stripped)
    return entries


def _validator_patterns() -> list[str]:
    validator_path = _repo_root() / "scripts" / "quest_validate-manifest.sh"
    patterns: list[str] = []
    in_patterns = False

    for line in validator_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped == "EXPECTED_PATTERNS=(":
            in_patterns = True
            continue
        if in_patterns and stripped == ")":
            break
        if in_patterns:
            match = re.search(r'"([^"]+)"', line)
            if match:
                patterns.append(match.group(1))

    return patterns


def test_manifest_lists_core_quest_helpers_and_tests() -> None:
    entries = _manifest_entries()

    assert {
        "scripts/quest_backfill_journal.py",
        "scripts/quest_complete.py",
        "scripts/quest_preflight.sh",
        "scripts/quest_state.py",
        "scripts/quest_celebrate/celebrate.py",
        "scripts/quest_celebrate/quest-celebrate.sh",
        "tests/unit/test_codex_skill_wrappers.py",
        "tests/unit/test_review_intelligence.py",
    } <= entries


def test_manifest_validator_patterns_cover_core_quest_helpers() -> None:
    patterns = _validator_patterns()
    expected_paths = {
        "scripts/quest_backfill_journal.py",
        "scripts/quest_complete.py",
        "scripts/quest_preflight.sh",
        "scripts/quest_state.py",
        "scripts/quest_celebrate/celebrate.py",
        "scripts/quest_celebrate/quest-celebrate.sh",
        "tests/unit/test_codex_skill_wrappers.py",
        "tests/unit/test_review_intelligence.py",
        "tests/unit/test_quest_manifest.py",
    }

    uncovered = sorted(
        path
        for path in expected_paths
        if not any(fnmatch.fnmatch(path, pattern) for pattern in patterns)
    )

    assert uncovered == []
