#!/usr/bin/env python3
"""Print the resolved engineering throughput runtime config."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engineering_throughput.config import build_argument_parser, print_run_config, resolve_run_config


def main(argv: list[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    config = resolve_run_config(args)
    return print_run_config(config)


if __name__ == "__main__":
    raise SystemExit(main())
