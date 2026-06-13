"""Strict XAUUSD M5 scalping setup analyzer.

The analyzer is designed for a scheduled runner that supplies fresh candles every
five minutes. It returns exactly one actionable setup only when every configured
gate is satisfied; otherwise it returns the required no-trade message.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import median
from typing import Any, Iterable, Literal, Mapping, Sequence

NO_TRADE_MESSAGE = "No trade – conditions not met"

Direction = Literal["Buy", "Sell"]
Bias = Literal["Bullish", "Bearish"]


@dataclass(frozen=True)
class Candle:
    """OHLCV candle."""

    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def bullish(self) -> bool:
        return self.close > self.open

    @property
    def bearish(self) -> bool:
        return self.close < self.open

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low


@dataclass(frozen=True)
class MarketSnapshot:
    """Candles required for a single XAUUSD analysis pass."""

    m5: tuple[Candle, ...]
    m15: tuple[Candle, ...]
    h1: tuple[Candle, ...]


@dataclass(frozen=True)
class ScalpingConfig:
    """Execution gates for the institutional scalping checklist."""

    min_score: float = 7.0
    min_rr: float = 2.0
    max_trades_per_session: int = 2
    min_atr: float = 0.7
    london_start_hour_utc: int = 7
    london_end_hour_utc: int = 12
    new_york_start_hour_utc: int = 12
    new_york_end_hour_utc: int = 21


@dataclass(frozen=True)
class Sweep:
    direction: Direction
    level: float
    candle_index: int
    extreme: float
    kind: str


@dataclass(frozen=True)
class Zone:
    low: float
    high: float
    candle_index: int


@dataclass(frozen=True)
class TradeSignal:
    market_bias: Bias
    setup_type: Direction
    entry: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    risk_reward: float
    score: float
    confirmation: str
    reasoning: str

    def format_text(self) -> str:
        """Return the exact signal shape expected by the prompt."""

        return "\n".join(
            [
                f"Market Bias: {self.market_bias}",
                f"Setup Type: {self.setup_type}",
                f"Entry: {self.entry:.2f}",
                f"Stop Loss: {self.stop_loss:.2f}",
                f"Take Profits: TP1 {self.take_profit_1:.2f}, TP2 {self.take_profit_2:.2f}",
                f"Risk/Reward: 1:{self.risk_reward:.2f}",
                f"Score: {self.score:.1f}/10",
                f"Confirmation: {self.confirmation}",
                f"Reasoning: {self.reasoning}",
            ]
        )


def analyze_market(
    snapshot: MarketSnapshot,
    *,
    now: datetime | None = None,
    session_trade_count: int = 0,
    config: ScalpingConfig | None = None,
) -> TradeSignal | None:
    """Analyze one market snapshot and return a single high-probability setup."""

    cfg = config or ScalpingConfig()
    now = _as_utc(now or snapshot.m5[-1].time if snapshot.m5 else datetime.now(timezone.utc))

    if _session_name(now, cfg) is None:
        return None
    if session_trade_count >= cfg.max_trades_per_session:
        return None
    if len(snapshot.m5) < 60 or len(snapshot.m15) < 35 or len(snapshot.h1) < 20:
        return None

    closes_m5 = [c.close for c in snapshot.m5]
    ema20 = _ema(closes_m5, 20)
    ema50 = _ema(closes_m5, 50)
    rsi = _rsi(closes_m5, 14)
    adx = _adx(snapshot.m5, 14)
    atr_values = _atr_series(snapshot.m5, 14)
    if not ema20 or not ema50 or rsi is None or adx is None or not atr_values:
        return None

    atr = atr_values[-1]
    if _low_volatility(snapshot.m5, atr_values, cfg):
        return None

    bias = _higher_timeframe_bias(snapshot.m15, snapshot.h1)
    sweep = _latest_liquidity_sweep(snapshot.m5, atr)
    if sweep is None:
        return None

    direction = sweep.direction
    if (direction == "Buy" and bias != "Bullish") or (direction == "Sell" and bias != "Bearish"):
        return None

    latest = snapshot.m5[-1]
    displacement = _is_displacement(latest, atr)
    confirmation = _confirmed_entry(snapshot.m5, sweep, atr, displacement)
    if confirmation is None:
        return None

    if not _ema_aligned(direction, ema20[-1], ema50[-1], latest.close):
        return None
    if not _rsi_valid(direction, rsi):
        return None
    if adx <= 20 and not displacement:
        return None

    order_block = _order_block(snapshot.m5, direction, sweep.candle_index)
    fvg = _has_recent_fvg(snapshot.m5, direction)
    if order_block is None or not fvg:
        return None

    if not _structure_shift(snapshot.m5, direction, sweep.candle_index):
        return None

    signal = _build_signal(
        bias=bias,
        direction=direction,
        latest=latest,
        sweep=sweep,
        order_block=order_block,
        atr=atr,
        adx=adx,
        rsi=rsi,
        ema20=ema20[-1],
        ema50=ema50[-1],
        config=cfg,
    )
    if signal.score < cfg.min_score or signal.risk_reward < cfg.min_rr:
        return None
    return signal


def load_snapshot(payload: Mapping[str, Any]) -> MarketSnapshot:
    """Load a snapshot from JSON-compatible data.

    Accepted keys are case-insensitive among ``m5``, ``m15`` and ``h1``. Each
    candle must include ``time`` (or ``timestamp``), ``open``, ``high``, ``low``
    and ``close``. ``volume`` is optional.
    """

    lower_payload = {str(key).lower(): value for key, value in payload.items()}
    return MarketSnapshot(
        m5=tuple(_parse_candles(lower_payload.get("m5", ()))),
        m15=tuple(_parse_candles(lower_payload.get("m15", ()))),
        h1=tuple(_parse_candles(lower_payload.get("h1", ()))),
    )


def _parse_candles(raw_candles: Iterable[Mapping[str, Any]]) -> list[Candle]:
    candles: list[Candle] = []
    for raw in raw_candles:
        time_value = raw.get("time", raw.get("timestamp"))
        if time_value is None:
            raise ValueError("Each candle requires a time or timestamp field")
        candle = Candle(
            time=_parse_datetime(time_value),
            open=float(raw["open"]),
            high=float(raw["high"]),
            low=float(raw["low"]),
            close=float(raw["close"]),
            volume=float(raw["volume"]) if raw.get("volume") is not None else None,
        )
        if candle.high < max(candle.open, candle.close) or candle.low > min(candle.open, candle.close):
            raise ValueError(f"Invalid OHLC candle at {candle.time.isoformat()}")
        candles.append(candle)
    candles.sort(key=lambda item: item.time)
    return candles


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return _as_utc(value)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    text = str(value)
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    return _as_utc(datetime.fromisoformat(text))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _session_name(now: datetime, cfg: ScalpingConfig) -> str | None:
    hour = now.hour + now.minute / 60
    if cfg.london_start_hour_utc <= hour < cfg.london_end_hour_utc:
        return "London"
    if cfg.new_york_start_hour_utc <= hour < cfg.new_york_end_hour_utc:
        return "New York"
    return None


def _ema(values: Sequence[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    seed = sum(values[:period]) / period
    result = [seed]
    multiplier = 2 / (period + 1)
    for value in values[period:]:
        result.append((value - result[-1]) * multiplier + result[-1])
    return result


def _rsi(values: Sequence[float], period: int) -> float | None:
    if len(values) <= period:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for previous, current in zip(values, values[1:]):
        change = current - previous
        gains.append(max(change, 0))
        losses.append(abs(min(change, 0)))
    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:]):
        average_gain = (average_gain * (period - 1) + gain) / period
        average_loss = (average_loss * (period - 1) + loss) / period
    if average_loss == 0:
        return 100.0
    relative_strength = average_gain / average_loss
    return 100 - (100 / (1 + relative_strength))


def _true_range(current: Candle, previous: Candle | None) -> float:
    if previous is None:
        return current.range
    return max(
        current.high - current.low,
        abs(current.high - previous.close),
        abs(current.low - previous.close),
    )


def _atr_series(candles: Sequence[Candle], period: int) -> list[float]:
    if len(candles) <= period:
        return []
    true_ranges = [_true_range(candles[0], None)]
    true_ranges.extend(_true_range(current, previous) for previous, current in zip(candles, candles[1:]))
    first = sum(true_ranges[1 : period + 1]) / period
    result = [first]
    for true_range in true_ranges[period + 1 :]:
        result.append((result[-1] * (period - 1) + true_range) / period)
    return result


def _adx(candles: Sequence[Candle], period: int) -> float | None:
    if len(candles) < period * 2 + 1:
        return None

    true_ranges: list[float] = []
    plus_dm: list[float] = []
    minus_dm: list[float] = []
    for previous, current in zip(candles, candles[1:]):
        up_move = current.high - previous.high
        down_move = previous.low - current.low
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0.0)
        true_ranges.append(_true_range(current, previous))

    atr = sum(true_ranges[:period])
    plus = sum(plus_dm[:period])
    minus = sum(minus_dm[:period])
    dx_values: list[float] = []

    for index in range(period, len(true_ranges)):
        atr = atr - (atr / period) + true_ranges[index]
        plus = plus - (plus / period) + plus_dm[index]
        minus = minus - (minus / period) + minus_dm[index]
        if atr == 0:
            dx_values.append(0.0)
            continue
        plus_di = 100 * plus / atr
        minus_di = 100 * minus / atr
        denominator = plus_di + minus_di
        dx_values.append(0.0 if denominator == 0 else 100 * abs(plus_di - minus_di) / denominator)

    if len(dx_values) < period:
        return None
    adx = sum(dx_values[:period]) / period
    for value in dx_values[period:]:
        adx = ((adx * (period - 1)) + value) / period
    return adx


def _low_volatility(candles: Sequence[Candle], atr_values: Sequence[float], cfg: ScalpingConfig) -> bool:
    atr = atr_values[-1]
    recent_bodies = [c.body for c in candles[-8:]]
    if atr < cfg.min_atr:
        return True
    if len(atr_values) >= 30 and atr < median(atr_values[-30:]) * 0.75:
        return True
    if sum(recent_bodies) / len(recent_bodies) < atr * 0.22:
        return True
    return False


def _higher_timeframe_bias(m15: Sequence[Candle], h1: Sequence[Candle]) -> Bias:
    score = 0
    for candles in (m15, h1):
        closes = [c.close for c in candles]
        ema20 = _ema(closes, 20)
        ema50 = _ema(closes, 50) if len(closes) >= 50 else []
        latest = candles[-1].close
        if ema20 and latest > ema20[-1]:
            score += 1
        elif ema20:
            score -= 1
        if ema50 and ema20 and ema20[-1] > ema50[-1]:
            score += 1
        elif ema50 and ema20:
            score -= 1

        swing_highs, swing_lows = _swings(candles[:-1], lookback=2)
        if swing_highs and latest > max(level for _, level in swing_highs[-5:]):
            score += 1
        if swing_lows and latest < min(level for _, level in swing_lows[-5:]):
            score -= 1
    return "Bullish" if score >= 0 else "Bearish"


def _swings(candles: Sequence[Candle], lookback: int) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    highs: list[tuple[int, float]] = []
    lows: list[tuple[int, float]] = []
    if len(candles) < lookback * 2 + 1:
        return highs, lows
    for index in range(lookback, len(candles) - lookback):
        window = candles[index - lookback : index + lookback + 1]
        candle = candles[index]
        if candle.high == max(item.high for item in window):
            highs.append((index, candle.high))
        if candle.low == min(item.low for item in window):
            lows.append((index, candle.low))
    return highs, lows


def _latest_liquidity_sweep(candles: Sequence[Candle], atr: float) -> Sweep | None:
    tolerance = max(0.4, atr * 0.16)
    start_index = max(10, len(candles) - 6)
    for index in range(len(candles) - 1, start_index - 1, -1):
        prior = candles[max(0, index - 42) : index]
        swing_highs, swing_lows = _swings(prior, lookback=2)
        current = candles[index]

        buy_side_level = _liquidity_level(swing_highs, side="high", tolerance=tolerance)
        if buy_side_level is not None and current.high > buy_side_level and current.close < buy_side_level:
            return Sweep("Sell", buy_side_level, index, current.high, "buy-side liquidity sweep")

        sell_side_level = _liquidity_level(swing_lows, side="low", tolerance=tolerance)
        if sell_side_level is not None and current.low < sell_side_level and current.close > sell_side_level:
            return Sweep("Buy", sell_side_level, index, current.low, "sell-side liquidity sweep")
    return None


def _liquidity_level(
    swings: Sequence[tuple[int, float]],
    *,
    side: Literal["high", "low"],
    tolerance: float,
) -> float | None:
    recent = list(swings[-12:])
    if not recent:
        return None

    equal_clusters: list[list[float]] = []
    for _, level in recent:
        matched = False
        for cluster in equal_clusters:
            if abs(level - cluster[-1]) <= tolerance:
                cluster.append(level)
                matched = True
                break
        if not matched:
            equal_clusters.append([level])

    clusters = [cluster for cluster in equal_clusters if len(cluster) >= 2]
    if clusters:
        ranked = sorted((sum(cluster) / len(cluster) for cluster in clusters), reverse=side == "high")
        return ranked[0]
    return recent[-1][1]


def _is_displacement(candle: Candle, atr: float) -> bool:
    if atr <= 0:
        return False
    return candle.body >= atr * 0.55 and candle.range >= atr * 0.9


def _confirmed_entry(
    candles: Sequence[Candle],
    sweep: Sweep,
    atr: float,
    displacement: bool,
) -> str | None:
    latest = candles[-1]
    previous = candles[-2]
    if sweep.candle_index < len(candles) - 4:
        return None

    if sweep.direction == "Buy":
        reclaimed = latest.close > sweep.level
        rejection = latest.lower_wick >= max(latest.body * 0.55, atr * 0.18)
        engulfing = latest.bullish and latest.close > previous.high
        impulse = latest.bullish and displacement
        if reclaimed and (rejection or impulse) and (engulfing or impulse):
            return "Sell-side liquidity sweep, bullish rejection/displacement, reclaim above swept low"
    else:
        reclaimed = latest.close < sweep.level
        rejection = latest.upper_wick >= max(latest.body * 0.55, atr * 0.18)
        engulfing = latest.bearish and latest.close < previous.low
        impulse = latest.bearish and displacement
        if reclaimed and (rejection or impulse) and (engulfing or impulse):
            return "Buy-side liquidity sweep, bearish rejection/displacement, reclaim below swept high"
    return None


def _ema_aligned(direction: Direction, ema20: float, ema50: float, close: float) -> bool:
    if direction == "Buy":
        return close > ema20 > ema50
    return close < ema20 < ema50


def _rsi_valid(direction: Direction, rsi: float) -> bool:
    if direction == "Buy":
        return 45 <= rsi <= 68
    return 32 <= rsi <= 55


def _order_block(candles: Sequence[Candle], direction: Direction, sweep_index: int) -> Zone | None:
    search_start = max(0, sweep_index - 10)
    search_end = min(len(candles) - 1, sweep_index + 1)
    candidates = range(search_end, search_start - 1, -1)
    if direction == "Buy":
        for index in candidates:
            candle = candles[index]
            if candle.bearish:
                return Zone(low=candle.low, high=max(candle.open, candle.close), candle_index=index)
    else:
        for index in candidates:
            candle = candles[index]
            if candle.bullish:
                return Zone(low=min(candle.open, candle.close), high=candle.high, candle_index=index)
    return None


def _has_recent_fvg(candles: Sequence[Candle], direction: Direction) -> bool:
    recent_start = max(2, len(candles) - 12)
    for index in range(recent_start, len(candles)):
        left = candles[index - 2]
        right = candles[index]
        if direction == "Buy" and left.high < right.low:
            return True
        if direction == "Sell" and left.low > right.high:
            return True
    return False


def _structure_shift(candles: Sequence[Candle], direction: Direction, sweep_index: int) -> bool:
    prior = candles[max(0, sweep_index - 24) : sweep_index]
    if len(prior) < 8:
        return False
    swing_highs, swing_lows = _swings(prior, lookback=2)
    latest = candles[-1]
    if direction == "Buy":
        local_high = max((level for _, level in swing_highs[-3:]), default=max(c.high for c in prior[-5:]))
        return latest.close > local_high or latest.close > candles[sweep_index - 1].high
    local_low = min((level for _, level in swing_lows[-3:]), default=min(c.low for c in prior[-5:]))
    return latest.close < local_low or latest.close < candles[sweep_index - 1].low


def _build_signal(
    *,
    bias: Bias,
    direction: Direction,
    latest: Candle,
    sweep: Sweep,
    order_block: Zone,
    atr: float,
    adx: float,
    rsi: float,
    ema20: float,
    ema50: float,
    config: ScalpingConfig,
) -> TradeSignal:
    buffer = max(0.25, atr * 0.12)
    entry = latest.close
    if direction == "Buy":
        stop_loss = min(sweep.extreme, order_block.low) - buffer
        risk = entry - stop_loss
        take_profit_1 = entry + risk * 2
        take_profit_2 = entry + risk * 3
    else:
        stop_loss = max(sweep.extreme, order_block.high) + buffer
        risk = stop_loss - entry
        take_profit_1 = entry - risk * 2
        take_profit_2 = entry - risk * 3

    if risk <= 0:
        return TradeSignal(
            market_bias=bias,
            setup_type=direction,
            entry=entry,
            stop_loss=stop_loss,
            take_profit_1=take_profit_1,
            take_profit_2=take_profit_2,
            risk_reward=0,
            score=0,
            confirmation="Invalid risk",
            reasoning="Stop loss is not beyond structure.",
        )

    score = 0.0
    score += 2.0
    score += 2.0
    score += 1.5
    score += 1.5
    score += 1.0 if adx > 20 else 0.7
    score += 1.0 if config.min_atr <= atr else 0.0
    score = min(score, 10.0)

    zone_text = f"{order_block.low:.2f}-{order_block.high:.2f}"
    reasoning = (
        f"{bias} HTF bias aligns with M5 {direction.lower()} setup; {sweep.kind} at "
        f"{sweep.level:.2f}; valid order block {zone_text}; EMA20/EMA50 aligned "
        f"({ema20:.2f}/{ema50:.2f}); RSI {rsi:.1f}, ADX {adx:.1f}. "
        "At TP1 close 50% and move SL to breakeven; hold TP2 only while momentum continues."
    )
    confirmation = (
        "Liquidity sweep with strong rejection/impulse candle and reclaim of the swept key level"
    )

    return TradeSignal(
        market_bias=bias,
        setup_type=direction,
        entry=entry,
        stop_loss=stop_loss,
        take_profit_1=take_profit_1,
        take_profit_2=take_profit_2,
        risk_reward=3.0,
        score=score,
        confirmation=confirmation,
        reasoning=reasoning,
    )
