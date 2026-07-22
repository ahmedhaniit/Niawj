"""Command-line entry point for scheduled XAUUSD scalping analysis."""

from __future__ import annotations

import argparse

from .strategy import (
    NO_TRADE,
    StrategyConfig,
    evaluate_xauusd_scalp,
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
    parser.add_argument("--now", help="Override signal time as an ISO timestamp")
    parser.add_argument(
        "--state",
        required=True,
        help="Persistent JSON state file used to enforce session signal limits",
    )
    parser.add_argument(
        "--max-trades-per-session",
        type=int,
        choices=(1, 2),
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
    config = StrategyConfig(max_session_trades=args.max_trades_per_session)

    result = evaluate_xauusd_scalp(m5, m15, h1, state=state, config=config, now=now)
    print(result)

    if result != NO_TRADE:
        record_session_trade(state, now or m5[-1].time, candle_time=m5[-1].time)
        save_trade_state(args.state, state)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
