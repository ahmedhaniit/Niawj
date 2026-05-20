from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Literal

from .indicators import adx, atr, ema, rsi
from .models import Candle, MarketSnapshot, TradeSetup, Zone

NO_TRADE_MESSAGE = "No trade – conditions not met"
Direction = Literal["buy", "sell"]


@dataclass(frozen=True)
class LiquiditySweep:
    direction: Direction
    level: float
    extreme: float
    candle: Candle
    index: int


class ScalpingStrategy:
    """Strict XAUUSD M5 scalping evaluator.

    The strategy intentionally returns no trade unless every major filter has
    evidence in the supplied candle snapshot. It does not fetch market data.
    """

    def __init__(
        self,
        *,
        max_session_trades: int = 2,
        min_risk_reward: float = 2.0,
        min_m5_atr: float = 1.0,
    ) -> None:
        self.max_session_trades = max_session_trades
        self.min_risk_reward = min_risk_reward
        self.min_m5_atr = min_m5_atr

    def evaluate(self, snapshot: MarketSnapshot, *, session_trade_count: int = 0) -> TradeSetup | None:
        if snapshot.symbol != "XAUUSD":
            return None
        if session_trade_count >= self.max_session_trades:
            return None
        if not self._is_london_or_new_york(snapshot.as_of):
            return None
        if len(snapshot.m5) < 60 or len(snapshot.m15) < 50 or len(snapshot.h1) < 50:
            return None

        h1_bias = self._timeframe_bias(snapshot.h1)
        m15_bias = self._timeframe_bias(snapshot.m15)
        if h1_bias is None or m15_bias is None or h1_bias != m15_bias:
            return None

        direction: Direction = "buy" if h1_bias == "Bullish" else "sell"
        m5_bias = self._timeframe_bias(snapshot.m5)
        if m5_bias != h1_bias:
            return None

        closes = [candle.close for candle in snapshot.m5]
        ema_20 = ema(closes, 20)
        ema_50 = ema(closes, 50)
        latest_ema_20 = ema_20[-1]
        latest_ema_50 = ema_50[-1]
        if direction == "buy" and not (latest_ema_20 > latest_ema_50 and closes[-1] > latest_ema_20):
            return None
        if direction == "sell" and not (latest_ema_20 < latest_ema_50 and closes[-1] < latest_ema_20):
            return None

        latest_rsi = rsi(closes)[-1]
        if latest_rsi is None:
            return None
        if direction == "buy" and not (45 <= latest_rsi <= 70):
            return None
        if direction == "sell" and not (30 <= latest_rsi <= 55):
            return None

        latest_atr = atr(snapshot.m5)[-1]
        latest_adx = adx(snapshot.m5)[-1]
        if latest_atr is None or latest_atr < self.min_m5_atr:
            return None

        sweep = self._latest_liquidity_sweep(snapshot.m5, direction, latest_atr)
        if sweep is None:
            return None

        has_confirmation = self._has_entry_confirmation(snapshot.m5, sweep, latest_atr)
        if not has_confirmation:
            return None

        strong_displacement = self._has_recent_displacement(snapshot.m5, direction, latest_atr)
        if (latest_adx is None or latest_adx <= 20) and not strong_displacement:
            return None

        structure_break = self._latest_structure_break(snapshot.m5, direction)
        if structure_break is None:
            return None

        order_block = self._latest_order_block(snapshot.m5, direction, latest_atr)
        fvg = self._latest_fvg(snapshot.m5, direction)
        if order_block is None or fvg is None:
            return None

        setup = self._build_setup(
            snapshot=snapshot,
            direction=direction,
            sweep=sweep,
            order_block=order_block,
            fvg=fvg,
            latest_atr=latest_atr,
            latest_adx=latest_adx,
            strong_displacement=strong_displacement,
            structure_break=structure_break,
        )
        if setup is None or setup.score < 7 or setup.risk_reward < self.min_risk_reward:
            return None
        return setup

    def format_signal(self, snapshot: MarketSnapshot, *, session_trade_count: int = 0) -> str:
        setup = self.evaluate(snapshot, session_trade_count=session_trade_count)
        return setup.format() if setup else NO_TRADE_MESSAGE

    @staticmethod
    def _is_london_or_new_york(moment: datetime) -> bool:
        current = moment.time()
        london = time(7, 0) <= current <= time(11, 30)
        new_york = time(12, 30) <= current <= time(16, 30)
        return london or new_york

    def _timeframe_bias(self, candles: tuple[Candle, ...]) -> str | None:
        if len(candles) < 50:
            return None
        closes = [candle.close for candle in candles]
        ema_20 = ema(closes, 20)[-1]
        ema_50 = ema(closes, 50)[-1]
        last_close = closes[-1]

        swing_highs, swing_lows = self._swings(candles, window=2)
        if len(swing_highs) >= 2 and len(swing_lows) >= 2:
            higher_high = swing_highs[-1][1] > swing_highs[-2][1]
            higher_low = swing_lows[-1][1] > swing_lows[-2][1]
            lower_high = swing_highs[-1][1] < swing_highs[-2][1]
            lower_low = swing_lows[-1][1] < swing_lows[-2][1]
            if higher_high and higher_low and ema_20 > ema_50 and last_close > ema_20:
                return "Bullish"
            if lower_high and lower_low and ema_20 < ema_50 and last_close < ema_20:
                return "Bearish"

        if ema_20 > ema_50 and last_close > ema_20:
            return "Bullish"
        if ema_20 < ema_50 and last_close < ema_20:
            return "Bearish"
        return None

    @staticmethod
    def _swings(candles: tuple[Candle, ...], *, window: int) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
        highs: list[tuple[int, float]] = []
        lows: list[tuple[int, float]] = []
        for index in range(window, len(candles) - window):
            candidate = candles[index]
            left = candles[index - window : index]
            right = candles[index + 1 : index + window + 1]
            if all(candidate.high > candle.high for candle in left + right):
                highs.append((index, candidate.high))
            if all(candidate.low < candle.low for candle in left + right):
                lows.append((index, candidate.low))
        return highs, lows

    def _latest_liquidity_sweep(
        self,
        candles: tuple[Candle, ...],
        direction: Direction,
        latest_atr: float,
    ) -> LiquiditySweep | None:
        tolerance = max(0.35, latest_atr * 0.18)
        lookback = candles[-35:-3]
        if direction == "buy":
            level = self._equal_liquidity_level(lookback, "low", tolerance)
            if level is None:
                return None
            for offset, candle in enumerate(candles[-3:], start=len(candles) - 3):
                if candle.low < level - tolerance * 0.15 and candle.close > level:
                    return LiquiditySweep("buy", level, candle.low, candle, offset)
        else:
            level = self._equal_liquidity_level(lookback, "high", tolerance)
            if level is None:
                return None
            for offset, candle in enumerate(candles[-3:], start=len(candles) - 3):
                if candle.high > level + tolerance * 0.15 and candle.close < level:
                    return LiquiditySweep("sell", level, candle.high, candle, offset)
        return None

    @staticmethod
    def _equal_liquidity_level(candles: tuple[Candle, ...], side: str, tolerance: float) -> float | None:
        if len(candles) < 8:
            return None
        values = [candle.low if side == "low" else candle.high for candle in candles]
        candidates: list[float] = []
        for index, value in enumerate(values):
            for other in values[index + 1 :]:
                if abs(value - other) <= tolerance:
                    candidates.append((value + other) / 2)
        if not candidates:
            return None
        latest_reference = values[-1]
        return min(candidates, key=lambda candidate: abs(candidate - latest_reference))

    def _has_entry_confirmation(
        self,
        candles: tuple[Candle, ...],
        sweep: LiquiditySweep,
        latest_atr: float,
    ) -> bool:
        latest = candles[-1]
        previous = candles[-2]
        if sweep.direction == "buy":
            rejection = sweep.candle.close > sweep.level and sweep.candle.lower_wick >= sweep.candle.body * 0.8
            engulfing = latest.close > latest.open and latest.close > previous.high and latest.open <= previous.close
            impulse = latest.close > sweep.candle.high and latest.body >= latest_atr * 0.55
            reclaim = latest.close > sweep.level
            return reclaim and (rejection or engulfing or impulse)

        rejection = sweep.candle.close < sweep.level and sweep.candle.upper_wick >= sweep.candle.body * 0.8
        engulfing = latest.close < latest.open and latest.close < previous.low and latest.open >= previous.close
        impulse = latest.close < sweep.candle.low and latest.body >= latest_atr * 0.55
        reclaim = latest.close < sweep.level
        return reclaim and (rejection or engulfing or impulse)

    @staticmethod
    def _has_recent_displacement(candles: tuple[Candle, ...], direction: Direction, latest_atr: float) -> bool:
        for candle in candles[-3:]:
            if direction == "buy" and candle.direction == "bullish" and candle.body >= latest_atr * 0.85:
                return True
            if direction == "sell" and candle.direction == "bearish" and candle.body >= latest_atr * 0.85:
                return True
        return False

    @staticmethod
    def _latest_structure_break(candles: tuple[Candle, ...], direction: Direction) -> str | None:
        lookback = candles[-24:-3]
        latest = candles[-1]
        previous = candles[-2]
        if len(lookback) < 10:
            return None
        if direction == "buy":
            break_level = max(candle.high for candle in lookback)
            if latest.close > break_level or (previous.close <= break_level and latest.close > previous.high):
                return "BOS"
        else:
            break_level = min(candle.low for candle in lookback)
            if latest.close < break_level or (previous.close >= break_level and latest.close < previous.low):
                return "BOS"
        return None

    @staticmethod
    def _latest_order_block(candles: tuple[Candle, ...], direction: Direction, latest_atr: float) -> Zone | None:
        search = range(len(candles) - 1, max(len(candles) - 18, 2), -1)
        for index in search:
            candle = candles[index]
            if direction == "buy" and candle.direction == "bullish" and candle.body >= latest_atr * 0.75:
                for prior in range(index - 1, max(index - 8, 0), -1):
                    prior_candle = candles[prior]
                    if prior_candle.direction == "bearish":
                        return Zone("Demand OB", prior_candle.low, prior_candle.high, prior_candle.timestamp)
            if direction == "sell" and candle.direction == "bearish" and candle.body >= latest_atr * 0.75:
                for prior in range(index - 1, max(index - 8, 0), -1):
                    prior_candle = candles[prior]
                    if prior_candle.direction == "bullish":
                        return Zone("Supply OB", prior_candle.low, prior_candle.high, prior_candle.timestamp)
        return None

    @staticmethod
    def _latest_fvg(candles: tuple[Candle, ...], direction: Direction) -> Zone | None:
        for index in range(len(candles) - 1, 1, -1):
            first = candles[index - 2]
            third = candles[index]
            if direction == "buy" and first.high < third.low:
                return Zone("Bullish FVG", first.high, third.low, third.timestamp)
            if direction == "sell" and first.low > third.high:
                return Zone("Bearish FVG", third.high, first.low, third.timestamp)
        return None

    def _build_setup(
        self,
        *,
        snapshot: MarketSnapshot,
        direction: Direction,
        sweep: LiquiditySweep,
        order_block: Zone,
        fvg: Zone,
        latest_atr: float,
        latest_adx: float | None,
        strong_displacement: bool,
        structure_break: str,
    ) -> TradeSetup | None:
        latest = snapshot.m5[-1]
        buffer = max(0.35, latest_atr * 0.15)
        if direction == "buy":
            entry = round(max(latest.close, sweep.level), 2)
            stop = round(min(sweep.extreme, order_block.low) - buffer, 2)
            risk = entry - stop
            if risk <= 0:
                return None
            tp1 = round(entry + risk * self.min_risk_reward, 2)
            tp2 = round(entry + risk * 3, 2)
            setup_type = "Buy from sell-side liquidity sweep into demand OB/FVG"
            confirmation = "Sell-side sweep, bullish rejection/displacement, and reclaim above swept liquidity"
        else:
            entry = round(min(latest.close, sweep.level), 2)
            stop = round(max(sweep.extreme, order_block.high) + buffer, 2)
            risk = stop - entry
            if risk <= 0:
                return None
            tp1 = round(entry - risk * self.min_risk_reward, 2)
            tp2 = round(entry - risk * 3, 2)
            setup_type = "Sell from buy-side liquidity sweep into supply OB/FVG"
            confirmation = "Buy-side sweep, bearish rejection/displacement, and reclaim below swept liquidity"

        score = 7
        if latest_adx is not None and latest_adx > 25:
            score += 1
        if strong_displacement:
            score += 1
        if self._zones_overlap(order_block, fvg):
            score += 1
        score = min(score, 10)

        risk_reward = abs(tp1 - entry) / risk
        if risk_reward < self.min_risk_reward:
            return None

        reasoning = (
            f"{snapshot.symbol} aligns {self._timeframe_bias(snapshot.h1)} on H1/M15; "
            f"M5 printed {structure_break} after sweeping liquidity at {sweep.level:.2f}. "
            f"{order_block.kind} {order_block.low:.2f}-{order_block.high:.2f} and "
            f"{fvg.kind} {fvg.low:.2f}-{fvg.high:.2f} support the entry. "
            "At TP1 close 50% and move SL to breakeven; let TP2 run only while momentum continues."
        )

        return TradeSetup(
            trade_type="Buy" if direction == "buy" else "Sell",
            entry=entry,
            stop_loss=stop,
            take_profit_1=tp1,
            take_profit_2=tp2,
            risk_reward=risk_reward,
            score=score,
            confirmation=confirmation,
            reasoning=reasoning,
            market_bias="Bullish" if direction == "buy" else "Bearish",
            setup_type=setup_type,
        )

    @staticmethod
    def _zones_overlap(first: Zone, second: Zone) -> bool:
        return first.low <= second.high and second.low <= first.high
