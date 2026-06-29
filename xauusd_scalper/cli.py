"""Command-line entry point for the XAUUSD scalping evaluator."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .strategy import analyze_snapshot, format_decision


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate one XAUUSD M5 market snapshot and print one setup or no-trade."
    )
    parser.add_argument(
        "snapshot",
        nargs="?",
        help="Path to a JSON market snapshot. Reads from stdin when omitted.",
    )
    args = parser.parse_args(argv)

    try:
        payload = read_payload(args.snapshot)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Invalid snapshot: {exc}", file=sys.stderr)
        return 2

    if not isinstance(payload, dict):
        print("Invalid snapshot: top-level JSON value must be an object", file=sys.stderr)
        return 2

    print(format_decision(analyze_snapshot(payload)))
    return 0


def read_payload(path: str | None) -> Any:
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return json.loads(sys.stdin.read())


if __name__ == "__main__":
    raise SystemExit(main())
