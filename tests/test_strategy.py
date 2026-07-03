from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from xauusd_scalper import (
    NO_TRADE,
    Candle,
    StrategyConfig,
    TradeState,
    active_session,
    evaluate_xauusd_scalp,
    session_key,
)


def _candle(time: datetime, open_: float, high: float, low: float, close: float) -> Candle:
    return Candle(time=time, open=open_, high=high, low=low, close=close)


def _trend_candles(
    count: int,
    *,
    end: datetime,
    minutes: int,
    price: float,
    step: float,
) -> list[Candle]:
    first_time = end - timedelta(minutes=minutes * (count - 1))
    candles: list[Candle] = []
    for index in range(count):
        base = price + index * step
        if step >= 0:
            open_ = base - 0.18
            close = base + 0.24
        else:
            open_ = base + 0.18
            close = base - 0.24
        high = max(open_, close) + 0.90
        low = min(open_, close) - 0.90
        candles.append(_candle(first_time + timedelta(minutes=minutes * index), open_, high, low, close))
    return candles


def _bullish_htf(end: datetime) -> tuple[list[Candle], list[Candle]]:
    return (
        _trend_candles(60, end=end, minutes=15, price=1985.0, step=0.55),
        _trend_candles(60, end=end, minutes=60, price=1940.0, step=1.20),
    )


def _mirror(candles: list[Candle], pivot: float = 4000.0) -> list[Candle]:
    return [
        _candle(
            candle.time,
            pivot - candle.open,
            pivot - candle.low,
            pivot - candle.high,
            pivot - candle.close,
        )
        for candle in candles
    ]


def _valid_buy_fixture() -> tuple[list[Candle], list[Candle], list[Candle]]:
    end = datetime(2026, 7, 3, 12, 5, tzinfo=timezone.utc)
    first_time = end - timedelta(minutes=5 * 59)
    m5: list[Candle] = []

    for index in range(58):
        anchor = 1998.0 + index * 0.18
        if index % 5 == 0:
            open_ = anchor + 0.12
            close = anchor - 0.06
        else:
            open_ = anchor - 0.14
            close = anchor + 0.22
        high = max(open_, close) + 0.85
        low = min(open_, close) - 0.85
        m5.append(_candle(first_time + timedelta(minutes=5 * index), open_, high, low, close))

    # Equal lows create sell-side liquidity for the later sweep.
    m5[-12] = _candle(m5[-12].time, 2008.20, 2009.10, 2004.00, 2008.70)
    m5[-7] = _candle(m5[-7].time, 2009.20, 2010.00, 2004.20, 2009.60)

    # Three-candle imbalance that remains valid when the confirmation candle prints.
    m5[-5] = _candle(m5[-5].time, 2004.80, 2005.30, 2004.00, 2005.00)
    m5[-3] = _candle(m5[-3].time, 2006.20, 2007.80, 2005.90, 2007.40)
    m5[-1] = _candle(m5[-1].time, 2004.80, 2005.30, 2004.00, 2005.00)

    sweep_time = end - timedelta(minutes=5)
    m5.append(_candle(sweep_time, 2010.20, 2011.00, 2003.40, 2006.10))
    m5.append(_candle(end, 2006.00, 2014.20, 2005.80, 2012.30))

    m15, h1 = _bullish_htf(end)
    return m5, m15, h1


class XauusdStrategyTests(unittest.TestCase):
    def test_returns_one_valid_buy_setup_when_all_conditions_align(self) -> None:
        m5, m15, h1 = _valid_buy_fixture()

        result = evaluate_xauusd_scalp(m5, m15, h1)

        self.assertNotEqual(NO_TRADE, result)
        self.assertIn("Market Bias: Bullish", result)
        self.assertIn("Setup Type: Buy", result)
        self.assertIn("Risk/Reward: 1:2.00", result)
        self.assertIn("Score:", result)
        self.assertIn("Sell-side liquidity sweep", result)
        self.assertIn("At TP1 close 50%", result)

    def test_returns_one_valid_sell_setup_when_bearish_conditions_align(self) -> None:
        m5, m15, h1 = _valid_buy_fixture()

        result = evaluate_xauusd_scalp(_mirror(m5), _mirror(m15), _mirror(h1))

        self.assertNotEqual(NO_TRADE, result)
        self.assertIn("Market Bias: Bearish", result)
        self.assertIn("Setup Type: Sell", result)
        self.assertIn("Risk/Reward: 1:2.00", result)
        self.assertIn("Buy-side liquidity sweep", result)

    def test_returns_no_trade_without_liquidity_sweep(self) -> None:
        m5, m15, h1 = _valid_buy_fixture()
        sweep = m5[-2]
        m5[-2] = _candle(sweep.time, sweep.open, sweep.high, 2007.20, 2007.30)

        self.assertEqual(NO_TRADE, evaluate_xauusd_scalp(m5, m15, h1))

    def test_returns_no_trade_in_low_volatility_chop(self) -> None:
        end = datetime(2026, 7, 3, 12, 5, tzinfo=timezone.utc)
        first_time = end - timedelta(minutes=5 * 69)
        m5 = [
            _candle(
                first_time + timedelta(minutes=5 * index),
                2000.00 + (0.03 if index % 2 else -0.03),
                2000.18,
                1999.82,
                2000.00 + (-0.03 if index % 2 else 0.03),
            )
            for index in range(70)
        ]
        m15, h1 = _bullish_htf(end)

        self.assertEqual(NO_TRADE, evaluate_xauusd_scalp(m5, m15, h1))

    def test_session_filter_blocks_outside_london_and_new_york(self) -> None:
        m5, m15, h1 = _valid_buy_fixture()
        result = evaluate_xauusd_scalp(m5, m15, h1, now=datetime(2026, 7, 3, 22, 0, tzinfo=timezone.utc))

        self.assertEqual(NO_TRADE, result)

    def test_session_trade_limit_blocks_third_setup(self) -> None:
        m5, m15, h1 = _valid_buy_fixture()
        now = datetime(2026, 7, 3, 12, 5, tzinfo=timezone.utc)
        self.assertEqual("New York", active_session(now))
        state = TradeState(session_trade_counts={session_key(now): {"New York": 2}})

        result = evaluate_xauusd_scalp(m5, m15, h1, state=state, now=now)

        self.assertEqual(NO_TRADE, result)

    def test_minimum_risk_reward_config_is_enforced(self) -> None:
        m5, m15, h1 = _valid_buy_fixture()

        result = evaluate_xauusd_scalp(m5, m15, h1, config=StrategyConfig(min_risk_reward=2.5))

        self.assertEqual(NO_TRADE, result)


if __name__ == "__main__":
    unittest.main()
