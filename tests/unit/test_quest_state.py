from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import pytest

_scripts_dir = str(Path(__file__).resolve().parent.parent.parent / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

import quest_state
from quest_runtime.state import OptimisticLockError, load_state, update_state


def _write_state(quest_dir: Path, *, phase: str, status: str = "pending") -> None:
    payload = {
        "phase": phase,
        "status": status,
        "updated_at": "2026-04-23T00:00:00Z",
    }
    (quest_dir / "state.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )


def test_update_state_applies_changes_when_expected_phase_matches(tmp_path: Path) -> None:
    quest_dir = tmp_path / "quest"
    quest_dir.mkdir()
    _write_state(quest_dir, phase="plan_reviewed")

    updated = update_state(
        quest_dir,
        expected_phase="plan_reviewed",
        phase="presenting",
        status="in_progress",
    )

    assert updated["phase"] == "presenting"
    assert updated["status"] == "in_progress"
    assert "updated_at" in updated
    assert load_state(quest_dir)["phase"] == "presenting"


def test_update_state_raises_when_expected_phase_no_longer_matches(tmp_path: Path) -> None:
    quest_dir = tmp_path / "quest"
    quest_dir.mkdir()
    _write_state(quest_dir, phase="reviewing")

    with pytest.raises(OptimisticLockError) as exc_info:
        update_state(
            quest_dir,
            expected_phase="plan_reviewed",
            phase="building",
        )

    assert exc_info.value.expected_phase == "plan_reviewed"
    assert exc_info.value.current_phase == "reviewing"
    assert load_state(quest_dir)["phase"] == "reviewing"


def test_main_rechecks_expected_phase_after_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    quest_dir = tmp_path / "quest"
    quest_dir.mkdir()
    _write_state(quest_dir, phase="plan_reviewed")

    monkeypatch.setattr(
        quest_state,
        "parse_args",
        lambda: argparse.Namespace(
            quest_dir=str(quest_dir),
            phase=None,
            transition="presenting",
            status="in_progress",
            expect_phase="plan_reviewed",
            last_role=None,
            last_verdict=None,
            quest_mode=None,
            plan_iteration=None,
            fix_iteration=None,
        ),
    )

    def fake_run_validator(target_quest_dir: str, _target_phase: str) -> tuple[int, str]:
        _write_state(Path(target_quest_dir), phase="presentation_complete", status="in_progress")
        return 0, ""

    monkeypatch.setattr(quest_state, "run_validator", fake_run_validator)

    assert quest_state.main() == 1
    assert "Optimistic lock failed" in capsys.readouterr().err
    assert load_state(quest_dir)["phase"] == "presentation_complete"
