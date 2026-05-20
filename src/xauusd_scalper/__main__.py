from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .models import MarketSnapshot
from .strategy import NO_TRADE_MESSAGE, ScalpingStrategy


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate a strict XAUUSD M5 scalping setup.")
    parser.add_argument("snapshot", nargs="?", help="Path to snapshot JSON. Reads stdin when omitted.")
    parser.add_argument(
        "--session-trades",
        type=int,
        default=0,
        help="Number of already accepted trades in the active London/New York session.",
    )
    args = parser.parse_args(argv)

    try:
        raw = _read_snapshot(args.snapshot)
        snapshot = MarketSnapshot.from_mapping(json.loads(raw))
        print(ScalpingStrategy().format_signal(snapshot, session_trade_count=args.session_trades))
    except (OSError, ValueError, json.JSONDecodeError):
        print(NO_TRADE_MESSAGE)
    return 0


def _read_snapshot(path: str | None) -> str:
    if path:
        return Path(path).read_text(encoding="utf-8")
    return sys.stdin.read()


if __name__ == "__main__":
    raise SystemExit(main())
