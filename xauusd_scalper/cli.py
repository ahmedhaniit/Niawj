"""Command-line entry point for the XAUUSD scalping analyzer."""

from __future__ import annotations

import argparse

from .strategy import (
    NO_TRADE,
    analyze_market,
    load_trade_state,
    parse_datetime,
    read_candles_csv,
    record_session_trade,
    save_trade_state,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze XAUUSD M5/M15/H1 OHLC candles and emit one strict scalping setup.",
    )
    parser.add_argument("--m5", required=True, help="CSV path for M5 candles")
    parser.add_argument("--m15", required=True, help="CSV path for M15 candles")
    parser.add_argument("--h1", required=True, help="CSV path for H1 candles")
    parser.add_argument("--now", help="Override current signal time as an ISO timestamp")
    parser.add_argument("--state", help="JSON file used to enforce max trades per session")
    parser.add_argument(
        "--record",
        action="store_true",
        help="Record a generated setup in --state after analysis",
    )
    parser.add_argument(
        "--max-trades-per-session",
        type=int,
        default=2,
        help="Maximum valid setups per London/New York session",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    m5 = read_candles_csv(args.m5)
    m15 = read_candles_csv(args.m15)
    h1 = read_candles_csv(args.h1)
    now = parse_datetime(args.now) if args.now else None
    state = load_trade_state(args.state)

    result = analyze_market(
        m5,
        m15,
        h1,
        now=now,
        trade_state=state if args.state else None,
        max_trades_per_session=args.max_trades_per_session,
    )
    print(result)

    if args.record and args.state and result != NO_TRADE:
        record_session_trade(state, now or m5[-1].time)
        save_trade_state(args.state, state)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
