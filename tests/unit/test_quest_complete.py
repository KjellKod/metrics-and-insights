from __future__ import annotations

import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

_scripts_dir = str(Path(__file__).resolve().parent.parent.parent / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

import quest_complete


def test_main_reports_invalid_date(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    quest_dir = tmp_path / "quest"
    quest_dir.mkdir()
    (quest_dir / "state.json").write_text(
        json.dumps({"status": "complete"}, indent=2) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(quest_complete, "load_quest_data", lambda _: SimpleNamespace())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "quest_complete.py",
            "--quest-dir",
            str(quest_dir),
            "--date",
            "2026-13-40",
        ],
    )

    assert quest_complete.main() == 1
    assert "invalid --date" in capsys.readouterr().err
