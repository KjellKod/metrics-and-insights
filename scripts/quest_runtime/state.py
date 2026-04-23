"""Helpers for updating quest state.json consistently."""

from __future__ import annotations

import fcntl
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class OptimisticLockError(RuntimeError):
    """Raised when state.json changed between validation and write."""

    def __init__(self, expected_phase: str, current_phase: Any) -> None:
        self.expected_phase = expected_phase
        self.current_phase = "unknown" if current_phase in (None, "") else str(current_phase)
        super().__init__(
            f"Optimistic lock failed: expected phase '{self.expected_phase}' "
            f"but state.json has '{self.current_phase}'."
        )


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def load_state(quest_dir: str | Path) -> dict[str, Any]:
    state_path = Path(quest_dir) / "state.json"
    return json.loads(state_path.read_text(encoding="utf-8"))


def write_state(quest_dir: str | Path, state: dict[str, Any]) -> Path:
    state_path = Path(quest_dir) / "state.json"
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return state_path


def update_state(
    quest_dir: str | Path,
    *,
    expected_phase: str | None = None,
    **updates: Any,
) -> dict[str, Any]:
    quest_dir = Path(quest_dir)
    lock_path = quest_dir / "state.json.lock"

    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        state = load_state(quest_dir)
        current_phase = state.get("phase", "unknown")
        if expected_phase is not None and current_phase != expected_phase:
            raise OptimisticLockError(expected_phase, current_phase)
        for key, value in updates.items():
            if value is not None:
                state[key] = value
        state["updated_at"] = utc_now_iso()
        write_state(quest_dir, state)
        return state
