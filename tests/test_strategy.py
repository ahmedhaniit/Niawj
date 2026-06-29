from __future__ import annotations

import unittest

from xauusd_scalper import NO_TRADE, analyze_snapshot


def valid_buy_snapshot() -> dict:
    return {
        "session": "London",
        "trades_taken_in_session": 0,
        "volatility": {"state": "normal", "choppy": False},
        "higher_timeframe": {
            "bias": "Bullish",
            "structure": "BOS",
            "liquidity_zones": ["2630.00 equal lows", "2647.50 prior high"],
        },
        "m5": {
            "trend": "Bullish",
            "structure_shift": "CHoCH",
            "momentum_shift": True,
        },
        "liquidity": {
            "sweep": True,
            "sweep_side": "sell-side",
            "buy_side": "2647.50",
            "sell_side": "2630.00",
        },
        "zones": {
            "demand": {"low": 2631.0, "high": 2632.0},
            "supply": {"low": 2647.0, "high": 2649.0},
            "order_block": {"type": "demand", "low": 2631.1, "high": 2631.9, "valid": True},
            "fvg": {"low": 2632.2, "high": 2633.1, "valid": True},
        },
        "indicators": {
            "ema20": 2634.4,
            "ema50": 2633.2,
            "rsi": 61.5,
            "adx": 24.8,
        },
        "confirmation": {
            "liquidity_sweep": True,
            "rejection_or_displacement": True,
            "candle": "engulfing",
            "reclaim_key_level": True,
        },
        "setup": {
            "type": "Buy",
            "entry": {"low": 2632.2, "high": 2632.9},
            "stop_loss": 2630.6,
            "take_profit_1": 2637.5,
            "take_profit_2": 2638.6,
            "stop_loss_basis": "structure swing low below swept liquidity",
            "score": 8,
        },
    }


class AnalyzeSnapshotTest(unittest.TestCase):
    def test_returns_formatted_trade_when_all_conditions_are_met(self) -> None:
        decision = analyze_snapshot(valid_buy_snapshot())

        self.assertTrue(decision.is_trade)
        self.assertIn("Market Bias: Bullish", decision.output)
        self.assertIn("Setup Type: Buy", decision.output)
        self.assertIn("Risk/Reward: 1:2.48", decision.output)
        self.assertIn("Score: 8/10", decision.output)

    def test_requires_liquidity_sweep(self) -> None:
        snapshot = valid_buy_snapshot()
        snapshot["liquidity"]["sweep"] = False
        snapshot["confirmation"]["liquidity_sweep"] = False

        decision = analyze_snapshot(snapshot)

        self.assertFalse(decision.is_trade)
        self.assertEqual(NO_TRADE, decision.output)
        self.assertIn("liquidity sweep is missing", decision.reasons)

    def test_rejects_low_volatility(self) -> None:
        snapshot = valid_buy_snapshot()
        snapshot["volatility"]["state"] = "low"

        decision = analyze_snapshot(snapshot)

        self.assertFalse(decision.is_trade)
        self.assertEqual(NO_TRADE, decision.output)

    def test_rejects_outside_london_or_new_york(self) -> None:
        snapshot = valid_buy_snapshot()
        snapshot["session"] = "Asia"

        decision = analyze_snapshot(snapshot)

        self.assertFalse(decision.is_trade)
        self.assertEqual(NO_TRADE, decision.output)

    def test_rejects_when_risk_reward_is_below_two(self) -> None:
        snapshot = valid_buy_snapshot()
        snapshot["setup"]["take_profit_1"] = 2634.5
        snapshot["setup"]["take_profit_2"] = 2636.0

        decision = analyze_snapshot(snapshot)

        self.assertFalse(decision.is_trade)
        self.assertEqual(NO_TRADE, decision.output)
        self.assertIn("risk/reward is below 1:2", decision.reasons)

    def test_rejects_more_than_two_session_trades(self) -> None:
        snapshot = valid_buy_snapshot()
        snapshot["trades_taken_in_session"] = 2

        decision = analyze_snapshot(snapshot)

        self.assertFalse(decision.is_trade)
        self.assertEqual(NO_TRADE, decision.output)


if __name__ == "__main__":
    unittest.main()
