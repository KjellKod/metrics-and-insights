from __future__ import annotations

from pathlib import Path


def test_skill_references_committed_scripts_not_ws_sources() -> None:
    text = Path(".skills/engineering-throughput-spreadsheet/SKILL.md").read_text(encoding="utf-8")

    assert "scripts/engineering_throughput_build.py" in text
    assert "scripts/engineering_throughput_show_config.py" in text
    assert "[--team-config <team-config.json>]" in text
    assert ".ws/github-throughput-2025-2026-expanded/collect_github_metrics.py" not in text
    assert ".ws/github-throughput-2025-2026-expanded/build_sheet_payload.py" not in text
