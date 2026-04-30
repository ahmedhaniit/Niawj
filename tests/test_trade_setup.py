import unittest
from datetime import time

from niawj.trade_setup import (
    NO_TRADE_MESSAGE,
    CandleSignal,
    HigherTimeframeContext,
    IndicatorContext,
    KeyZones,
    LiquidityContext,
    M5Structure,
    MarketSnapshot,
    PriceZone,
    SetupType,
    TradeCandidate,
    analyze_market,
    first_valid_setup,
)


def valid_buy_snapshot(**overrides):
    demand = PriceZone("M5 demand order block", 2335.10, 2335.90)
    swept_lows = PriceZone("equal lows", 2331.80, 2332.10)
    snapshot = MarketSnapshot(
        symbol="XAUUSD",
        timestamp_utc=time(8, 15),
        htf=HigherTimeframeContext(
            bias="Bullish",
            liquidity_zones=(PriceZone("H1 buy-side pool", 2352.00, 2353.20),),
            major_structure="BOS",
        ),
        m5=M5Structure(
            intraday_trend="Bullish",
            structure_event="CHoCH",
            momentum_shift=True,
        ),
        liquidity=LiquidityContext(
            equal_lows=(swept_lows,),
            buy_side_liquidity=(PriceZone("prior high", 2346.50, 2347.20),),
            sell_side_liquidity=(swept_lows,),
            swept_zone=swept_lows,
            sweep_direction="sell-side",
        ),
        key_zones=KeyZones(
            demand=(demand,),
            order_blocks=(demand,),
            fair_value_gaps=(PriceZone("bullish FVG", 2335.40, 2336.20),),
        ),
        indicators=IndicatorContext(
            ema20=2338.20,
            ema50=2335.70,
            rsi=58.0,
            adx=24.0,
        ),
        candidate=TradeCandidate(
            direction="Buy",
            setup_type=SetupType.LIQUIDITY_SWEEP_REVERSAL,
            entry_low=2335.20,
            entry_high=2335.80,
            stop_loss=2332.80,
            take_profit_1=2341.20,
            take_profit_2=2342.40,
            candle_signal=CandleSignal(
                engulfing=True,
                strong_rejection=True,
                displacement=True,
            ),
            reclaimed_level=2335.00,
            score=8,
            reason=(
                "London sweep of sell-side liquidity reclaimed M5 demand with "
                "EMA alignment and fresh bullish displacement."
            ),
        ),
    )

    return _replace(snapshot, **overrides)


class TradeSetupTests(unittest.TestCase):
    def test_valid_snapshot_returns_single_formatted_setup(self):
        result = analyze_market(valid_buy_snapshot())

        self.assertIn("Market Bias: Bullish", result)
        self.assertIn("Setup Type: Liquidity sweep reversal Buy", result)
        self.assertIn("Entry: 2335.20-2335.80", result)
        self.assertIn("Risk/Reward: 1:2.56", result)
        self.assertIn("Score: 8/10", result)
        self.assertIn("sell-side liquidity sweep", result)
        self.assertIn("At TP1 close 50%", result)

    def test_rejects_outside_london_and_new_york_sessions(self):
        self.assertEqual(
            analyze_market(valid_buy_snapshot(timestamp_utc=time(12, 0))),
            NO_TRADE_MESSAGE,
        )

    def test_rejects_after_two_trades_in_session(self):
        self.assertEqual(
            analyze_market(valid_buy_snapshot(session_trade_counts={"London": 2})),
            NO_TRADE_MESSAGE,
        )

    def test_rejects_missing_liquidity_sweep(self):
        liquidity = LiquidityContext(
            buy_side_liquidity=(PriceZone("prior high", 2346.50, 2347.20),),
            sell_side_liquidity=(PriceZone("equal lows", 2331.80, 2332.10),),
        )

        self.assertEqual(
            analyze_market(valid_buy_snapshot(liquidity=liquidity)),
            NO_TRADE_MESSAGE,
        )

    def test_rejects_low_risk_reward_candidate(self):
        candidate = _replace(
            valid_buy_snapshot().candidate,
            take_profit_2=2339.20,
        )

        self.assertEqual(
            analyze_market(valid_buy_snapshot(candidate=candidate)),
            NO_TRADE_MESSAGE,
        )

    def test_rejects_missing_candle_confirmation(self):
        candidate = _replace(
            valid_buy_snapshot().candidate,
            candle_signal=CandleSignal(engulfing=True),
        )

        self.assertEqual(
            analyze_market(valid_buy_snapshot(candidate=candidate)),
            NO_TRADE_MESSAGE,
        )

    def test_rejects_choppy_or_low_volatility_conditions(self):
        self.assertEqual(analyze_market(valid_buy_snapshot(choppy=True)), NO_TRADE_MESSAGE)
        self.assertEqual(
            analyze_market(valid_buy_snapshot(low_volatility=True)),
            NO_TRADE_MESSAGE,
        )

    def test_first_valid_setup_returns_only_one_setup(self):
        invalid = valid_buy_snapshot(timestamp_utc=time(20, 0))
        valid = valid_buy_snapshot()

        self.assertTrue(
            first_valid_setup((invalid, valid)).startswith("Market Bias: Bullish")
        )


def _replace(instance, **changes):
    values = instance.__dict__.copy()
    values.update(changes)
    return type(instance)(**values)


if __name__ == "__main__":
    unittest.main()
