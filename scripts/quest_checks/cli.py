"""Run the standard Quest validation and test commands."""

from __future__ import annotations

from collections.abc import Sequence
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

COMMANDS: list[tuple[str, list[str]]] = [
    ("validate quest config", ["bash", "scripts/quest_validate-quest-config.sh"]),
    ("validate manifest", ["bash", "scripts/quest_validate-manifest.sh"]),
    ("validate handoff contracts", ["bash", "scripts/quest_validate-handoff-contracts.sh"]),
    ("integration tests", ["bash", "tests/integration/test-enforce-allowlist.sh"]),
    ("unit tests", [sys.executable, "-m", "pytest", "tests/unit"]),
]


def run_commands(commands: Sequence[tuple[str, Sequence[str]]]) -> int:
    for label, command in commands:
        rendered = [str(part) for part in command]
        print(f"==> {label}: {' '.join(rendered)}", flush=True)
        completed = subprocess.run(rendered, cwd=REPO_ROOT, check=False)
        if completed.returncode != 0:
            return completed.returncode
    return 0


def main() -> int:
    return run_commands(COMMANDS)


if __name__ == "__main__":
    raise SystemExit(main())
