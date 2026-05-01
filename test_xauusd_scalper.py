import unittest

from xauusd_scalper import (
    Bias,
    CandleConfirmation,
    Direction,
    EntryConfirmation,
    HigherTimeframeContext,
    Indicators,
    KeyZones,
    LiquidityContext,
    LiquiditySide,
    M5Structure,
    MarketSnapshot,
    NO_TRADE,
    Session,
    StructureEvent,
    TradeCandidate,
    generate_trade_setup,
)


def bullish_snapshot(**overrides):
    snapshot = MarketSnapshot(
        session=Session.LONDON,
        session_trade_counts={Session.LONDON: 1},
        high_timeframe=HigherTimeframeContext(
            bias=Bias.BULLISH,
            key_liquidity_zones=["2404.80 equal lows", "2420.00 buy stops"],
            major_structure=StructureEvent.BOS,
        ),
        m5_structure=M5Structure(
            trend=Bias.BULLISH,
            event=StructureEvent.CHOCH,
            momentum_shift=True,
        ),
        liquidity=LiquidityContext(
            equal_highs=True,
            equal_lows=True,
            liquidity_sweep=True,
            swept_side=LiquiditySide.SELL_SIDE,
            buy_side_liquidity=["2416.50 equal highs"],
            sell_side_liquidity=["2404.80 equal lows"],
        ),
        key_zones=KeyZones(
            supply_zone=(2416.50, 2418.20),
            demand_zone=(2405.20, 2406.10),
            order_block=(2405.20, 2406.10),
            fair_value_gap=(2407.10, 2408.00),
        ),
        indicators=Indicators(
            ema20=2408.50,
            ema50=2406.40,
            rsi=57.0,
            adx=24.0,
            strong_displacement_candle=False,
        ),
        candidates=(
            TradeCandidate(
                direction=Direction.BUY,
                entry=(2406.20, 2406.80),
                stop_loss=2403.80,
                take_profit_1=2412.20,
                take_profit_2=2414.60,
                score=8,
                setup_type="Demand retest after sell-side liquidity sweep",
                confirmation=EntryConfirmation(
                    liquidity_sweep=True,
                    strong_rejection=True,
                    displacement=False,
                    candle_confirmation=CandleConfirmation.ENGULFING,
                    key_level_reclaimed=True,
                ),
                reason=(
                    "M15/H1 bullish bias aligned with M5 CHoCH after sell-side "
                    "liquidity sweep; demand order block and FVG support entry."
                ),
            ),
        ),
    )
    return snapshot.__class__(**(snapshot.__dict__ | overrides))


class XauusdScalperTest(unittest.TestCase):
    def test_returns_single_valid_setup_when_all_conditions_are_met(self):
        result = generate_trade_setup(bullish_snapshot())

        self.assertIn("Market Bias: Bullish", result)
        self.assertIn("Setup Type: Demand retest", result)
        self.assertIn("Entry: 2406.20-2406.80", result)
        self.assertIn("Risk/Reward: 1:3.00", result)
        self.assertIn("Score: 8/10", result)
        self.assertIn("liquidity sweep + strong rejection", result)

    def test_returns_no_trade_outside_london_or_new_york(self):
        result = generate_trade_setup(bullish_snapshot(session=Session.OTHER))

        self.assertEqual(NO_TRADE, result)

    def test_returns_no_trade_after_two_session_trades(self):
        result = generate_trade_setup(
            bullish_snapshot(session_trade_counts={Session.LONDON: 2})
        )

        self.assertEqual(NO_TRADE, result)

    def test_returns_no_trade_in_choppy_or_low_volatility_conditions(self):
        self.assertEqual(NO_TRADE, generate_trade_setup(bullish_snapshot(choppy_conditions=True)))
        self.assertEqual(NO_TRADE, generate_trade_setup(bullish_snapshot(low_volatility=True)))

    def test_returns_no_trade_without_liquidity_sweep_confirmation(self):
        no_sweep = bullish_snapshot(
            liquidity=LiquidityContext(
                equal_highs=True,
                equal_lows=True,
                liquidity_sweep=False,
                swept_side=LiquiditySide.SELL_SIDE,
                buy_side_liquidity=["2416.50 equal highs"],
                sell_side_liquidity=["2404.80 equal lows"],
            )
        )

        self.assertEqual(NO_TRADE, generate_trade_setup(no_sweep))

    def test_returns_no_trade_when_risk_reward_is_below_minimum(self):
        candidate = bullish_snapshot().candidates[0]
        weak_reward = candidate.__class__(
            **(candidate.__dict__ | {"take_profit_2": 2410.00})
        )

        self.assertEqual(
            NO_TRADE,
            generate_trade_setup(bullish_snapshot(candidates=(weak_reward,))),
        )

    def test_returns_no_trade_when_entry_confirmation_is_missing(self):
        candidate = bullish_snapshot().candidates[0]
        unconfirmed = candidate.__class__(
            **(
                candidate.__dict__
                | {
                    "confirmation": EntryConfirmation(
                        liquidity_sweep=True,
                        strong_rejection=False,
                        displacement=False,
                        candle_confirmation=CandleConfirmation.ENGULFING,
                        key_level_reclaimed=True,
                    )
                }
            )
        )

        self.assertEqual(
            NO_TRADE,
            generate_trade_setup(bullish_snapshot(candidates=(unconfirmed,))),
        )

    def test_returns_no_trade_when_ema_alignment_disagrees_with_bias(self):
        result = generate_trade_setup(
            bullish_snapshot(
                indicators=Indicators(
                    ema20=2406.40,
                    ema50=2408.50,
                    rsi=57.0,
                    adx=24.0,
                    strong_displacement_candle=False,
                )
            )
        )

        self.assertEqual(NO_TRADE, result)


if __name__ == "__main__":
    unittest.main()
