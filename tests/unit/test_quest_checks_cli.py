from __future__ import annotations

import importlib.util
from pathlib import Path
import runpy
import subprocess
from types import SimpleNamespace

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _cli_path() -> Path:
    return _repo_root() / "scripts" / "quest_checks" / "cli.py"


def _load_cli_module():
    spec = importlib.util.spec_from_file_location("quest_checks_cli", _cli_path())
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_references_existing_repo_commands() -> None:
    module = _load_cli_module()
    missing_paths: list[str] = []

    for _, command in module.COMMANDS:
        for token in command[1:]:
            if token.startswith(("scripts/", "tests/")) and not (_repo_root() / token).exists():
                missing_paths.append(token)

    assert missing_paths == []


def test_cli_entrypoint_executes_main(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_cli_module()
    calls: list[tuple[list[str], Path, bool]] = []

    def fake_run(command: list[str], cwd: Path, check: bool) -> SimpleNamespace:
        calls.append((command, cwd, check))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(_cli_path()), run_name="__main__")

    assert exc_info.value.code == 0
    assert [command for command, _, _ in calls] == [command for _, command in module.COMMANDS]
    assert all(cwd == module.REPO_ROOT for _, cwd, _ in calls)
    assert all(check is False for _, _, check in calls)
