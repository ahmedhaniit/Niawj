import unittest
from datetime import datetime, timedelta, timezone

from xauusd_scalper import (
    NO_TRADE,
    Candle,
    StrategyConfig,
    TradeState,
    evaluate_xauusd_scalp,
)


def _candle(time, open_, high, low, close):
    return Candle(time=time, open=open_, high=high, low=low, close=close)


def _trend_candles(count, *, start, step, minutes, end_time):
    first_time = end_time - timedelta(minutes=minutes * (count - 1))
    candles = []
    for index in range(count):
        anchor = start + index * step
        open_ = anchor - step * 0.25
        close = anchor + step * 0.45
        if step < 0:
            open_ = anchor - step * 0.25
            close = anchor + step * 0.45
        high = max(open_, close) + 1.2
        low = min(open_, close) - 1.2
        candles.append(_candle(first_time + timedelta(minutes=minutes * index), open_, high, low, close))
    return candles


def _valid_buy_fixture():
    end = datetime(2026, 7, 1, 12, 5, tzinfo=timezone.utc)
    first_time = end - timedelta(minutes=5 * 59)
    candles = []
    for index in range(57):
        anchor = 1998.0 + index * 0.18
        open_ = anchor - 0.15
        close = anchor + (0.25 if index % 3 else -0.05)
        high = max(open_, close) + 0.9
        low = min(open_, close) - 0.9
        candles.append(_candle(first_time + timedelta(minutes=5 * index), open_, high, low, close))

    # Most recent equal lows create sell-side liquidity.
    candles[-12] = _candle(candles[-12].time, 2008.20, 2009.10, 2004.00, 2008.70)
    candles[-7] = _candle(candles[-7].time, 2009.20, 2010.00, 2004.20, 2009.60)

    # A bullish FVG exists before the confirmation candle.
    candles[-5] = _candle(candles[-5].time, 2004.80, 2005.30, 2004.00, 2005.00)
    candles[-3] = _candle(candles[-3].time, 2006.20, 2007.80, 2005.90, 2007.40)

    previous_time = end - timedelta(minutes=5)
    current_time = end
    candles.append(_candle(previous_time, 2010.20, 2011.00, 2004.30, 2006.10))
    candles.append(_candle(current_time, 2006.00, 2014.20, 2003.40, 2012.30))

    m15 = _trend_candles(40, start=1990, step=0.9, minutes=15, end_time=end)
    h1 = _trend_candles(40, start=1950, step=2.1, minutes=60, end_time=end)
    return candles, m15, h1


class XauusdStrategyTests(unittest.TestCase):
    def test_returns_valid_buy_setup_when_all_conditions_align(self):
        m5, m15, h1 = _valid_buy_fixture()

        result = evaluate_xauusd_scalp(m5, m15, h1)

        self.assertIn("Market Bias: Bullish", result)
        self.assertIn("Setup Type: Buy after sell-side liquidity sweep", result)
        self.assertIn("Risk/Reward: 1:2.00", result)
        self.assertIn("Score:", result)
        self.assertNotEqual(NO_TRADE, result)

    def test_returns_no_trade_without_liquidity_sweep(self):
        m5, m15, h1 = _valid_buy_fixture()
        last = m5[-1]
        m5[-1] = _candle(last.time, last.open, last.high, 2004.20, last.close)

        self.assertEqual(NO_TRADE, evaluate_xauusd_scalp(m5, m15, h1))

    def test_returns_no_trade_outside_london_and_new_york_sessions(self):
        m5, m15, h1 = _valid_buy_fixture()
        shifted = []
        for candle in m5:
            shifted.append(
                Candle(
                    time=candle.time.replace(hour=22),
                    open=candle.open,
                    high=candle.high,
                    low=candle.low,
                    close=candle.close,
                )
            )

        self.assertEqual(NO_TRADE, evaluate_xauusd_scalp(shifted, m15, h1))

    def test_returns_no_trade_after_two_signals_in_session(self):
        m5, m15, h1 = _valid_buy_fixture()
        state = TradeState(session_trade_counts={"New York": 2})

        self.assertEqual(NO_TRADE, evaluate_xauusd_scalp(m5, m15, h1, state=state))

    def test_returns_no_trade_if_minimum_risk_reward_is_not_available(self):
        m5, m15, h1 = _valid_buy_fixture()
        config = StrategyConfig(min_risk_reward=2.5)

        self.assertEqual(NO_TRADE, evaluate_xauusd_scalp(m5, m15, h1, config=config))


if __name__ == "__main__":
    unittest.main()
