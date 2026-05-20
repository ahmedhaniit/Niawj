from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from xauusd_scalper.models import Candle, MarketSnapshot
from xauusd_scalper.strategy import NO_TRADE_MESSAGE, ScalpingStrategy


def candle(index: int, open_: float, high: float, low: float, close: float) -> Candle:
    start = datetime(2026, 5, 20, 7, 0, tzinfo=timezone.utc)
    return Candle(start + timedelta(minutes=5 * index), open_, high, low, close)


def trend_candles(count: int, *, start: float, step: float, minutes: int) -> tuple[Candle, ...]:
    candles: list[Candle] = []
    timestamp = datetime(2026, 5, 19, 0, 0, tzinfo=timezone.utc)
    previous_close = start
    for index in range(count):
        open_ = previous_close
        close = start + (index + 1) * step
        high = max(open_, close) + 0.75
        low = min(open_, close) - 0.75
        candles.append(Candle(timestamp + timedelta(minutes=minutes * index), open_, high, low, close))
        previous_close = close
    return tuple(candles)


def bullish_m5_setup() -> tuple[Candle, ...]:
    candles: list[Candle] = []
    price = 2400.0
    for index in range(45):
        open_ = price
        close = price + (0.28 if index % 3 else -0.08)
        high = max(open_, close) + 0.55
        low = min(open_, close) - 0.55
        candles.append(candle(index, open_, high, low, close))
        price = close

    pullback = [
        (2410.20, 2410.80, 2408.90, 2409.20),
        (2409.20, 2409.75, 2408.20, 2408.55),
        (2408.55, 2409.20, 2407.20, 2407.75),
        (2407.75, 2408.40, 2406.48, 2407.20),
        (2407.20, 2408.10, 2406.95, 2407.60),
        (2407.60, 2408.35, 2406.50, 2407.05),
        (2407.05, 2407.90, 2406.92, 2407.45),
        (2407.45, 2408.20, 2406.49, 2407.10),
        (2407.10, 2407.85, 2406.96, 2407.50),
        (2407.50, 2408.25, 2406.52, 2407.15),
        (2407.15, 2407.95, 2406.90, 2407.40),
        (2407.40, 2408.05, 2406.54, 2407.05),
    ]
    for values in pullback:
        candles.append(candle(len(candles), *values))

    candles.extend(
        [
            candle(57, 2407.05, 2407.30, 2405.95, 2406.90),
            candle(58, 2406.90, 2408.00, 2406.80, 2407.60),
            candle(59, 2407.60, 2411.70, 2407.55, 2411.20),
        ]
    )
    return tuple(candles)


class ScalpingStrategyTest(unittest.TestCase):
    def test_returns_valid_buy_setup_when_all_rules_align(self) -> None:
        snapshot = MarketSnapshot(
            symbol="XAUUSD",
            as_of=datetime(2026, 5, 20, 11, 0, tzinfo=timezone.utc),
            m5=bullish_m5_setup(),
            m15=trend_candles(60, start=2380.0, step=0.45, minutes=15),
            h1=trend_candles(60, start=2350.0, step=1.25, minutes=60),
        )

        setup = ScalpingStrategy(min_m5_atr=0.5).evaluate(snapshot)

        self.assertIsNotNone(setup)
        assert setup is not None
        self.assertEqual(setup.market_bias, "Bullish")
        self.assertIn("Buy", setup.setup_type)
        self.assertGreaterEqual(setup.risk_reward, 2.0)
        self.assertGreaterEqual(setup.score, 7)

    def test_low_volatility_chop_returns_no_trade(self) -> None:
        flat = tuple(candle(index, 2400.0, 2400.25, 2399.75, 2400.02) for index in range(60))
        snapshot = MarketSnapshot(
            symbol="XAUUSD",
            as_of=datetime(2026, 5, 20, 12, 35, tzinfo=timezone.utc),
            m5=flat,
            m15=flat[:50],
            h1=flat[:50],
        )

        self.assertEqual(ScalpingStrategy().format_signal(snapshot), NO_TRADE_MESSAGE)

    def test_session_trade_limit_returns_no_trade(self) -> None:
        snapshot = MarketSnapshot(
            symbol="XAUUSD",
            as_of=datetime(2026, 5, 20, 11, 0, tzinfo=timezone.utc),
            m5=bullish_m5_setup(),
            m15=trend_candles(60, start=2380.0, step=0.45, minutes=15),
            h1=trend_candles(60, start=2350.0, step=1.25, minutes=60),
        )

        signal = ScalpingStrategy(min_m5_atr=0.5).format_signal(snapshot, session_trade_count=2)

        self.assertEqual(signal, NO_TRADE_MESSAGE)


if __name__ == "__main__":
    unittest.main()
