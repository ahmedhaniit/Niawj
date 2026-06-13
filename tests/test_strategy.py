from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xauusd_scalper import Candle, MarketSnapshot, NO_TRADE_MESSAGE, analyze_market


def candle(index: int, open_: float, high: float, low: float, close: float) -> Candle:
    return Candle(
        time=datetime(2026, 6, 13, 7, 0, tzinfo=timezone.utc) + timedelta(minutes=5 * index),
        open=open_,
        high=high,
        low=low,
        close=close,
    )


def trend(count: int, start: float, step: float, minutes: int) -> tuple[Candle, ...]:
    candles = []
    current = start
    for index in range(count):
        open_ = current
        close = current + step * 0.7
        high = max(open_, close) + 0.55
        low = min(open_, close) - 0.55
        candles.append(
            Candle(
                time=datetime(2026, 6, 13, tzinfo=timezone.utc) + timedelta(minutes=minutes * index),
                open=open_,
                high=high,
                low=low,
                close=close,
            )
        )
        current += step
    return tuple(candles)


def flat_m5() -> tuple[Candle, ...]:
    candles = []
    for index in range(65):
        base = 3300 + (0.03 if index % 2 else -0.03)
        candles.append(candle(index, base, base + 0.15, base - 0.15, base + 0.02))
    return tuple(candles)


def bullish_m5() -> tuple[Candle, ...]:
    candles = list(trend(52, 3300.0, 0.23, 5))
    candles.extend(
        [
            candle(52, 3311.90, 3312.70, 3310.90, 3311.30),
            candle(53, 3311.30, 3312.10, 3310.70, 3311.80),
            candle(54, 3313.40, 3315.20, 3313.10, 3314.90),
            candle(55, 3314.90, 3315.50, 3311.80, 3312.90),
            candle(56, 3312.70, 3313.20, 3309.90, 3311.50),
            candle(57, 3311.50, 3313.20, 3310.70, 3312.80),
            candle(58, 3312.80, 3313.90, 3310.80, 3311.40),
            candle(59, 3311.10, 3315.40, 3309.40, 3314.60),
        ]
    )
    return tuple(candles)


def bearish_m5() -> tuple[Candle, ...]:
    candles = list(trend(52, 3315.0, -0.23, 5))
    candles.extend(
        [
            candle(52, 3303.10, 3304.10, 3302.30, 3303.70),
            candle(53, 3303.70, 3304.30, 3302.90, 3303.20),
            candle(54, 3301.60, 3301.90, 3299.80, 3300.10),
            candle(55, 3300.10, 3303.20, 3299.50, 3302.10),
            candle(56, 3302.10, 3305.10, 3301.80, 3303.30),
            candle(57, 3303.30, 3304.30, 3301.80, 3302.20),
            candle(58, 3302.20, 3304.20, 3301.10, 3303.40),
            candle(59, 3303.70, 3305.60, 3299.60, 3300.20),
        ]
    )
    return tuple(candles)


class StrategyTests(unittest.TestCase):
    def test_low_volatility_returns_no_trade(self) -> None:
        snapshot = MarketSnapshot(
            m5=flat_m5(),
            m15=trend(55, 3300.0, 0.1, 15),
            h1=trend(55, 3290.0, 0.2, 60),
        )

        signal = analyze_market(snapshot, now=datetime(2026, 6, 13, 8, 0, tzinfo=timezone.utc))

        self.assertIsNone(signal)
        self.assertEqual(NO_TRADE_MESSAGE, "No trade – conditions not met")

    def test_session_trade_cap_blocks_signal(self) -> None:
        snapshot = MarketSnapshot(
            m5=bullish_m5(),
            m15=trend(55, 3305.0, 0.28, 15),
            h1=trend(55, 3280.0, 0.45, 60),
        )

        signal = analyze_market(
            snapshot,
            now=datetime(2026, 6, 13, 8, 0, tzinfo=timezone.utc),
            session_trade_count=2,
        )

        self.assertIsNone(signal)

    def test_valid_buy_setup_is_returned(self) -> None:
        snapshot = MarketSnapshot(
            m5=bullish_m5(),
            m15=trend(55, 3305.0, 0.28, 15),
            h1=trend(55, 3280.0, 0.45, 60),
        )

        signal = analyze_market(snapshot, now=datetime(2026, 6, 13, 8, 0, tzinfo=timezone.utc))

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.setup_type, "Buy")
        self.assertEqual(signal.market_bias, "Bullish")
        self.assertGreaterEqual(signal.score, 7)
        self.assertGreaterEqual(signal.risk_reward, 2)

    def test_valid_sell_setup_is_returned(self) -> None:
        snapshot = MarketSnapshot(
            m5=bearish_m5(),
            m15=trend(55, 3310.0, -0.28, 15),
            h1=trend(55, 3340.0, -0.45, 60),
        )

        signal = analyze_market(snapshot, now=datetime(2026, 6, 13, 13, 0, tzinfo=timezone.utc))

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.setup_type, "Sell")
        self.assertEqual(signal.market_bias, "Bearish")
        self.assertGreaterEqual(signal.score, 7)
        self.assertGreaterEqual(signal.risk_reward, 2)


if __name__ == "__main__":
    unittest.main()
