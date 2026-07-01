"""Strict XAUUSD M5 scalping evaluator.

The module is intentionally dependency-free so it can run inside a lightweight
automation every five minutes.  It does not guess when data is missing: any
missing mandatory confirmation returns the exact no-trade response.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Literal


NO_TRADE = "No trade – conditions not met"
Direction = Literal["Buy", "Sell"]
Bias = Literal["Bullish", "Bearish"]


@dataclass(frozen=True)
class Candle:
    """OHLC candle for one timeframe."""

    time: datetime
    open: float
    high: float
    low: float
    close: float

    def __post_init__(self) -> None:
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("candle high/low must contain open and close")

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

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
class Zone:
    """Supply/demand or imbalance zone."""

    low: float
    high: float

    def contains(self, price: float) -> bool:
        return self.low <= price <= self.high


@dataclass(frozen=True)
class TradeState:
    """Executed signal counts for the current trading day/session."""

    session_trade_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class StrategyConfig:
    """Tunable but conservative defaults for XAUUSD M5 scalping."""

    max_session_trades: int = 2
    equal_level_tolerance: float = 0.75
    sweep_break_buffer: float = 0.10
    structure_buffer: float = 0.30
    min_risk_reward: float = 2.0
    min_average_range: float = 0.70
    min_adx: float = 20.0
    impulse_range_multiplier: float = 1.30
    impulse_body_fraction: float = 0.55
    buy_rsi_ceiling: float = 80.0
    sell_rsi_floor: float = 20.0


@dataclass(frozen=True)
class TradeSetup:
    trade_type: Direction
    entry: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    risk_reward: float
    score: int
    confirmation: str
    reasoning: str
    market_bias: Bias
    setup_type: str

    def format(self) -> str:
        return "\n".join(
            [
                f"Market Bias: {self.market_bias}",
                f"Setup Type: {self.setup_type}",
                f"Entry: {self.entry:.2f}",
                f"Stop Loss: {self.stop_loss:.2f}",
                f"Take Profits: TP1 {self.take_profit_1:.2f}, TP2 {self.take_profit_2:.2f}",
                f"Risk/Reward: 1:{self.risk_reward:.2f}",
                f"Score: {self.score}/10",
                f"Confirmation: {self.confirmation}",
                f"Reasoning: {self.reasoning}",
            ]
        )


def evaluate_xauusd_scalp(
    m5_candles: Iterable[Candle],
    m15_candles: Iterable[Candle],
    h1_candles: Iterable[Candle],
    *,
    state: TradeState | None = None,
    config: StrategyConfig | None = None,
) -> str:
    """Return one valid setup or the strict no-trade response.

    The latest M5 candle is treated as the confirmation candle.  The function is
    pure: callers that execute a signal should persist/update TradeState outside
    this evaluator so duplicate automation runs do not mutate hidden state.
    """

    cfg = config or StrategyConfig()
    session_state = state or TradeState()
    m5 = list(m5_candles)
    m15 = list(m15_candles)
    h1 = list(h1_candles)

    if len(m5) < 60 or len(m15) < 35 or len(h1) < 35:
        return NO_TRADE

    session = active_session(m5[-1].time)
    if session is None:
        return NO_TRADE
    if session_state.session_trade_counts.get(session, 0) >= cfg.max_session_trades:
        return NO_TRADE

    htf_bias = _higher_timeframe_bias(m15, h1)
    if htf_bias is None:
        return NO_TRADE

    ema20 = _ema([c.close for c in m5], 20)[-1]
    ema50 = _ema([c.close for c in m5], 50)[-1]
    rsi = _rsi([c.close for c in m5], 14)
    adx = _adx(m5, 14)
    displacement = _is_displacement(m5, cfg)
    if not _has_tradeable_volatility(m5, adx, displacement, cfg):
        return NO_TRADE

    sweep = _detect_liquidity_sweep(m5, cfg)
    if sweep is None:
        return NO_TRADE
    direction, swept_level = sweep

    if direction == "Buy":
        if htf_bias != "Bullish" or not (ema20 > ema50) or rsi >= cfg.buy_rsi_ceiling:
            return NO_TRADE
    else:
        if htf_bias != "Bearish" or not (ema20 < ema50) or rsi <= cfg.sell_rsi_floor:
            return NO_TRADE

    if not _candle_confirmation(m5, direction, displacement):
        return NO_TRADE

    order_block = _find_order_block(m5, direction, cfg)
    if order_block is None:
        return NO_TRADE

    fvg = _find_fvg(m5, direction)
    if fvg is None:
        return NO_TRADE

    setup = _build_setup(
        direction=direction,
        market_bias=htf_bias,
        candles=m5,
        swept_level=swept_level,
        order_block=order_block,
        fvg=fvg,
        adx=adx,
        displacement=displacement,
        config=cfg,
    )
    if setup is None or setup.score < 7 or setup.risk_reward < cfg.min_risk_reward:
        return NO_TRADE

    return setup.format()


def active_session(timestamp: datetime) -> str | None:
    """Return the active trade session for a UTC timestamp.

    London and New York overlap; after New York opens, the setup is attributed to
    New York so each execution is counted against one session only.
    """

    utc_time = timestamp
    if utc_time.tzinfo is None:
        utc_time = utc_time.replace(tzinfo=timezone.utc)
    else:
        utc_time = utc_time.astimezone(timezone.utc)

    hour = utc_time.hour + utc_time.minute / 60
    if 12 <= hour < 21:
        return "New York"
    if 7 <= hour < 12:
        return "London"
    return None


def _higher_timeframe_bias(m15: list[Candle], h1: list[Candle]) -> Bias | None:
    m15_bias = _timeframe_bias(m15)
    h1_bias = _timeframe_bias(h1)
    if m15_bias == h1_bias:
        return m15_bias
    return None


def _timeframe_bias(candles: list[Candle]) -> Bias | None:
    closes = [c.close for c in candles]
    ema20 = _ema(closes, 20)[-1]
    ema50 = _ema(closes, 50)[-1]
    recent = candles[-12:]
    previous = candles[-24:-12]
    if not previous:
        return None
    broke_high = max(c.high for c in recent) > max(c.high for c in previous)
    broke_low = min(c.low for c in recent) < min(c.low for c in previous)
    if ema20 > ema50 and closes[-1] > ema20 and broke_high:
        return "Bullish"
    if ema20 < ema50 and closes[-1] < ema20 and broke_low:
        return "Bearish"
    return None


def _has_tradeable_volatility(
    candles: list[Candle],
    adx: float,
    displacement: bool,
    config: StrategyConfig,
) -> bool:
    average_range = sum(c.range for c in candles[-20:-1]) / 19
    return average_range >= config.min_average_range and (adx > config.min_adx or displacement)


def _detect_liquidity_sweep(
    candles: list[Candle],
    config: StrategyConfig,
) -> tuple[Direction, float] | None:
    current = candles[-1]
    prior = candles[-31:-1]
    equal_high = _equal_level(prior, "high", config.equal_level_tolerance)
    equal_low = _equal_level(prior, "low", config.equal_level_tolerance)

    if (
        equal_low is not None
        and current.low < equal_low - config.sweep_break_buffer
        and current.close > equal_low
    ):
        return "Buy", equal_low
    if (
        equal_high is not None
        and current.high > equal_high + config.sweep_break_buffer
        and current.close < equal_high
    ):
        return "Sell", equal_high
    return None


def _equal_level(candles: list[Candle], side: Literal["high", "low"], tolerance: float) -> float | None:
    levels = [c.high if side == "high" else c.low for c in candles]
    for index in range(len(levels) - 1, 1, -1):
        level = levels[index]
        for other in reversed(levels[: index - 1]):
            if abs(level - other) <= tolerance:
                return (level + other) / 2
    return None


def _candle_confirmation(candles: list[Candle], direction: Direction, displacement: bool) -> bool:
    current = candles[-1]
    previous = candles[-2]
    if direction == "Buy":
        engulfing = current.bullish and previous.bearish and current.close > previous.open
        impulse = current.bullish and displacement and current.close > previous.high
        reclaimed = current.close > previous.high or engulfing
    else:
        engulfing = current.bearish and previous.bullish and current.close < previous.open
        impulse = current.bearish and displacement and current.close < previous.low
        reclaimed = current.close < previous.low or engulfing
    return (engulfing or impulse) and reclaimed


def _find_order_block(
    candles: list[Candle],
    direction: Direction,
    config: StrategyConfig,
) -> Zone | None:
    start = max(1, len(candles) - 16)
    for index in range(len(candles) - 2, start - 1, -1):
        candidate = candles[index]
        next_candle = candles[index + 1]
        local_displacement = next_candle.range >= _average_range(candles[: index + 1], 12) * config.impulse_range_multiplier
        if direction == "Buy" and candidate.bearish and next_candle.bullish and local_displacement:
            return Zone(low=candidate.low, high=max(candidate.open, candidate.close))
        if direction == "Sell" and candidate.bullish and next_candle.bearish and local_displacement:
            return Zone(low=min(candidate.open, candidate.close), high=candidate.high)
    return None


def _find_fvg(candles: list[Candle], direction: Direction) -> Zone | None:
    for index in range(len(candles) - 1, max(1, len(candles) - 18), -1):
        first = candles[index - 2]
        third = candles[index]
        if direction == "Buy" and third.low > first.high:
            return Zone(low=first.high, high=third.low)
        if direction == "Sell" and third.high < first.low:
            return Zone(low=third.high, high=first.low)
    return None


def _build_setup(
    *,
    direction: Direction,
    market_bias: Bias,
    candles: list[Candle],
    swept_level: float,
    order_block: Zone,
    fvg: Zone,
    adx: float,
    displacement: bool,
    config: StrategyConfig,
) -> TradeSetup | None:
    current = candles[-1]
    entry = round(current.close, 2)
    if direction == "Buy":
        stop_loss = round(min(current.low, order_block.low) - config.structure_buffer, 2)
        risk = entry - stop_loss
        if risk <= 0:
            return None
        tp1 = round(entry + risk * config.min_risk_reward, 2)
        tp2 = round(entry + risk * 3, 2)
        setup_type = "Buy after sell-side liquidity sweep into demand OB/FVG"
        confirmation = "Sell-side sweep, bullish impulse/engulfing candle, and reclaim above swept liquidity"
    else:
        stop_loss = round(max(current.high, order_block.high) + config.structure_buffer, 2)
        risk = stop_loss - entry
        if risk <= 0:
            return None
        tp1 = round(entry - risk * config.min_risk_reward, 2)
        tp2 = round(entry - risk * 3, 2)
        setup_type = "Sell after buy-side liquidity sweep into supply OB/FVG"
        confirmation = "Buy-side sweep, bearish impulse/engulfing candle, and reclaim below swept liquidity"

    risk_reward = abs(tp1 - entry) / risk
    if risk_reward < config.min_risk_reward:
        return None

    score = 7
    if adx > 25:
        score += 1
    if displacement:
        score += 1
    if fvg.contains(entry) or order_block.contains(entry):
        score += 1
    score = min(score, 10)

    reasoning = (
        f"{market_bias} M15/H1 bias aligns with M5 EMA 20/50; liquidity at {swept_level:.2f} "
        f"was swept and reclaimed; structure stop is beyond the order block and sweep extreme; "
        "TP1 closes 50% and moves stop to breakeven, TP2 runs only while momentum continues."
    )

    return TradeSetup(
        trade_type=direction,
        entry=entry,
        stop_loss=stop_loss,
        take_profit_1=tp1,
        take_profit_2=tp2,
        risk_reward=risk_reward,
        score=score,
        confirmation=confirmation,
        reasoning=reasoning,
        market_bias=market_bias,
        setup_type=setup_type,
    )


def _average_range(candles: list[Candle], period: int) -> float:
    sample = candles[-period:] if len(candles) >= period else candles
    if not sample:
        return 0.0
    return sum(c.range for c in sample) / len(sample)


def _is_displacement(candles: list[Candle], config: StrategyConfig) -> bool:
    current = candles[-1]
    previous_average = _average_range(candles[-21:-1], 20)
    if previous_average <= 0 or current.range <= 0:
        return False
    return (
        current.range >= previous_average * config.impulse_range_multiplier
        and current.body / current.range >= config.impulse_body_fraction
    )


def _ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (period + 1)
    result = [values[0]]
    for value in values[1:]:
        result.append(value * alpha + result[-1] * (1 - alpha))
    return result


def _rsi(values: list[float], period: int) -> float:
    if len(values) <= period:
        return 50.0
    gains: list[float] = []
    losses: list[float] = []
    for previous, current in zip(values[-period - 1 : -1], values[-period:]):
        change = current - previous
        gains.append(max(change, 0))
        losses.append(abs(min(change, 0)))
    average_gain = sum(gains) / period
    average_loss = sum(losses) / period
    if average_loss == 0:
        return 100.0
    relative_strength = average_gain / average_loss
    return 100 - (100 / (1 + relative_strength))


def _adx(candles: list[Candle], period: int) -> float:
    if len(candles) < period + 2:
        return 0.0

    true_ranges: list[float] = []
    plus_dm: list[float] = []
    minus_dm: list[float] = []
    for previous, current in zip(candles[-period - 1 : -1], candles[-period:]):
        high_move = current.high - previous.high
        low_move = previous.low - current.low
        plus_dm.append(high_move if high_move > low_move and high_move > 0 else 0.0)
        minus_dm.append(low_move if low_move > high_move and low_move > 0 else 0.0)
        true_ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )

    true_range = sum(true_ranges)
    if true_range == 0:
        return 0.0
    plus_di = 100 * sum(plus_dm) / true_range
    minus_di = 100 * sum(minus_dm) / true_range
    denominator = plus_di + minus_di
    if denominator == 0:
        return 0.0
    return 100 * abs(plus_di - minus_di) / denominator
