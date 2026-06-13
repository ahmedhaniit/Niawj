"""Command line entry point for the XAUUSD scalping analyzer."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .strategy import (
    NO_TRADE_MESSAGE,
    ScalpingConfig,
    analyze_market,
    load_snapshot,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze XAUUSD candles and print one strict M5 scalping setup or no trade."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to JSON containing m5, m15 and h1 candle arrays.",
    )
    parser.add_argument(
        "--now",
        help="UTC timestamp for session filtering. Defaults to latest M5 candle time.",
    )
    parser.add_argument(
        "--session-trades",
        type=int,
        default=0,
        help="Trades already emitted for the active session when no state file is used.",
    )
    parser.add_argument(
        "--state-file",
        help="Optional JSON state file used to persist per-session signal counts.",
    )
    args = parser.parse_args()

    payload = _read_json(Path(args.input))
    snapshot = load_snapshot(payload)
    now = _parse_now(args.now) if args.now else (snapshot.m5[-1].time if snapshot.m5 else datetime.now(timezone.utc))
    cfg = ScalpingConfig()

    state_path = Path(args.state_file) if args.state_file else None
    state = _read_state(state_path) if state_path else {}
    state_key = _state_key(now, cfg)
    session_trade_count = int(state.get(state_key, args.session_trades))

    signal = analyze_market(
        snapshot,
        now=now,
        session_trade_count=session_trade_count,
        config=cfg,
    )

    if signal is None:
        print(NO_TRADE_MESSAGE)
        return 0

    print(signal.format_text())
    if state_path:
        state[state_key] = session_trade_count + 1
        _write_state(state_path, state)
    return 0


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("Input JSON must be an object with m5, m15 and h1 keys")
    return data


def _parse_now(value: str) -> datetime:
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _read_state(path: Path | None) -> dict[str, int]:
    if path is None or not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        return {}
    return {str(key): int(value) for key, value in raw.items()}


def _write_state(path: Path, state: dict[str, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _state_key(now: datetime, cfg: ScalpingConfig) -> str:
    hour = now.hour + now.minute / 60
    session = "london"
    if cfg.new_york_start_hour_utc <= hour < cfg.new_york_end_hour_utc:
        session = "new-york"
    return f"{now.date().isoformat()}:{session}"


if __name__ == "__main__":
    raise SystemExit(main())
