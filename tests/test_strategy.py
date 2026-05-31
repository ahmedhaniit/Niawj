from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from xauusd_scalper.strategy import (
    NO_TRADE,
    Candle,
    active_session,
    analyze_market,
    session_key,
)


def trend_candles(
    count: int,
    *,
    start: datetime,
    minutes: int,
    price: float,
    step: float,
) -> list[Candle]:
    candles: list[Candle] = []
    for index in range(count):
        base = price + index * step
        if step >= 0:
            open_price = base
            close_price = base + abs(step) * 0.65 + 0.05
            high = close_price + 0.30
            low = open_price - 0.20
        else:
            open_price = base
            close_price = base - abs(step) * 0.65 - 0.05
            high = open_price + 0.20
            low = close_price - 0.30
        candles.append(
            Candle(
                time=start + timedelta(minutes=index * minutes),
                open=open_price,
                high=high,
                low=low,
                close=close_price,
            )
        )
    return candles


def bullish_htf() -> tuple[list[Candle], list[Candle]]:
    start = datetime(2026, 5, 29, tzinfo=timezone.utc)
    m15 = trend_candles(60, start=start, minutes=15, price=2280.0, step=0.45)
    h1 = trend_candles(60, start=start, minutes=60, price=2240.0, step=1.00)
    return m15, h1


def valid_bullish_m5() -> list[Candle]:
    start = datetime(2026, 5, 31, 6, 15, tzinfo=timezone.utc)
    candles = trend_candles(67, start=start, minutes=5, price=2300.0, step=0.15)

    candle_67_time = start + timedelta(minutes=67 * 5)
    candles.append(
        Candle(
            time=candle_67_time,
            open=2310.00,
            high=2310.20,
            low=2309.40,
            close=2309.70,
        )
    )

    reference_low = min(candle.low for candle in candles[-18:])
    candles.append(
        Candle(
            time=candle_67_time + timedelta(minutes=5),
            open=2309.60,
            high=2310.00,
            low=reference_low - 1.00,
            close=reference_low + 0.20,
        )
    )
    candles.append(
        Candle(
            time=candle_67_time + timedelta(minutes=10),
            open=2310.30,
            high=2312.60,
            low=2310.25,
            close=2312.30,
        )
    )
    return candles


class StrategyTest(unittest.TestCase):
    def test_valid_bullish_setup_returns_single_formatted_trade(self) -> None:
        m15, h1 = bullish_htf()
        result = analyze_market(
            valid_bullish_m5(),
            m15,
            h1,
            now=datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc),
        )

        self.assertNotEqual(NO_TRADE, result)
        self.assertIn("Market Bias: Bullish", result)
        self.assertIn("Setup Type: Buy", result)
        self.assertIn("Risk/Reward: 1:2.00", result)
        self.assertIn("Score: 10/10", result)
        self.assertIn("liquidity sweep", result)

    def test_choppy_or_incomplete_conditions_return_no_trade(self) -> None:
        start = datetime(2026, 5, 31, 7, 0, tzinfo=timezone.utc)
        choppy_m5 = [
            Candle(
                time=start + timedelta(minutes=index * 5),
                open=2300.0 + (0.10 if index % 2 else -0.10),
                high=2300.40,
                low=2299.60,
                close=2300.0 + (-0.10 if index % 2 else 0.10),
            )
            for index in range(70)
        ]
        m15, h1 = bullish_htf()

        result = analyze_market(
            choppy_m5,
            m15,
            h1,
            now=datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(NO_TRADE, result)

    def test_session_filter_blocks_out_of_session(self) -> None:
        m15, h1 = bullish_htf()

        result = analyze_market(
            valid_bullish_m5(),
            m15,
            h1,
            now=datetime(2026, 5, 31, 3, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(NO_TRADE, result)

    def test_session_trade_limit_blocks_third_signal(self) -> None:
        m15, h1 = bullish_htf()
        now = datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)
        session = active_session(now)
        self.assertEqual("new_york", session)
        state = {session_key(now): {session: 2}}

        result = analyze_market(
            valid_bullish_m5(),
            m15,
            h1,
            now=now,
            trade_state=state,
        )

        self.assertEqual(NO_TRADE, result)


if __name__ == "__main__":
    unittest.main()
