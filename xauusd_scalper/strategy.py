"""Strict, dependency-free XAUUSD M5 scalping evaluator.

The evaluator is designed for scheduled execution after each fresh 5-minute
candle. It only emits one formatted setup when every mandatory condition is
present; otherwise it returns the exact no-trade response.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Literal


NO_TRADE = "No trade – conditions not met"
Direction = Literal["Buy", "Sell"]
Bias = Literal["Bullish", "Bearish"]
SessionName = Literal["London", "New York"]


@dataclass(frozen=True)
class Candle:
    """OHLCV candle for one timeframe."""

    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def __post_init__(self) -> None:
        if self.high < max(self.open, self.close):
            raise ValueError("candle high must contain open and close")
        if self.low > min(self.open, self.close):
            raise ValueError("candle low must contain open and close")
        if self.high < self.low:
            raise ValueError("candle high must be greater than or equal to low")

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


@dataclass(frozen=True)
class Zone:
    """Supply, demand, order-block, or fair-value-gap zone."""

    kind: str
    low: float
    high: float

    def contains(self, price: float) -> bool:
        return self.low <= price <= self.high


@dataclass(frozen=True)
class Sweep:
    """Liquidity sweep details used by entry confirmation."""

    direction: Direction
    index: int
    level: float
    extreme: float
    liquidity_side: str


@dataclass
class TradeState:
    """Per-day, per-session generated setup counts.

    The evaluator is pure apart from reading this state; callers should call
    :func:`record_session_trade` after executing or recording a non-no-trade
    setup.
    """

    session_trade_counts: dict[str, dict[str, int]] = field(default_factory=dict)

    @classmethod
    def from_legacy_counts(cls, counts: dict[str, int]) -> "TradeState":
        """Build state from a simple current-day session-count mapping."""

        today = datetime.now(timezone.utc).date().isoformat()
        return cls(session_trade_counts={today: dict(counts)})


@dataclass(frozen=True)
class StrategyConfig:
    """Conservative defaults for XAUUSD M5 scalping."""

    max_session_trades: int = 2
    min_risk_reward: float = 2.0
    min_average_range: float = 0.60
    equal_level_tolerance: float = 0.70
    sweep_break_buffer: float = 0.10
    structure_buffer: float = 0.25
    min_adx: float = 20.0
    impulse_range_multiplier: float = 1.25
    impulse_body_fraction: float = 0.55
    buy_rsi_floor: float = 35.0
    buy_rsi_ceiling: float = 78.0
    sell_rsi_floor: float = 22.0
    sell_rsi_ceiling: float = 65.0
    sweep_scan_candles: int = 5
    structure_lookback: int = 14


@dataclass(frozen=True)
class TradeSetup:
    """Validated trade setup ready for user-facing formatting."""

    trade_type: Direction
    market_bias: Bias
    setup_type: str
    entry: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    risk_reward: float
    score: int
    confirmation: str
    reasoning: str

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


def parse_datetime(raw: str) -> datetime:
    """Parse ISO timestamps and normalize them to UTC."""

    value = raw.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def read_candles_csv(path: str | Path) -> list[Candle]:
    """Read candles from CSV with time, open, high, low, close columns."""

    candles: list[Candle] = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"time", "open", "high", "low", "close"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Missing required candle columns: {', '.join(sorted(missing))}")

        for row in reader:
            candles.append(
                Candle(
                    time=parse_datetime(row["time"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row.get("volume") or 0.0),
                )
            )

    return sorted(candles, key=lambda candle: candle.time)


def load_trade_state(path: str | Path | None) -> TradeState:
    """Load persisted per-session trade counts."""

    if path is None:
        return TradeState()
    state_path = Path(path)
    if not state_path.exists():
        return TradeState()
    with state_path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("Trade state must be a JSON object")

    # Preferred shape: {"2026-07-03": {"London": 1, "New York": 0}}
    if all(isinstance(value, dict) for value in data.values()):
        return TradeState(
            session_trade_counts={
                str(day): {str(session): int(count) for session, count in sessions.items()}
                for day, sessions in data.items()
            }
        )

    # Backward-compatible shape: {"London": 1, "New York": 0}
    return TradeState.from_legacy_counts({str(session): int(count) for session, count in data.items()})


def save_trade_state(path: str | Path, state: TradeState) -> None:
    """Persist per-session trade counts."""

    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with state_path.open("w", encoding="utf-8") as handle:
        json.dump(state.session_trade_counts, handle, indent=2, sort_keys=True)
        handle.write("\n")


def active_session(timestamp: datetime) -> SessionName | None:
    """Return the active London/New York session for a UTC timestamp.

    During the overlap, setups are attributed to New York so a setup is counted
    against one session only.
    """

    utc_time = timestamp
    if utc_time.tzinfo is None:
        utc_time = utc_time.replace(tzinfo=timezone.utc)
    else:
        utc_time = utc_time.astimezone(timezone.utc)

    minutes = utc_time.hour * 60 + utc_time.minute
    if 12 * 60 <= minutes < 21 * 60:
        return "New York"
    if 7 * 60 <= minutes < 12 * 60:
        return "London"
    return None


def session_key(timestamp: datetime) -> str:
    """Return the UTC date key used for session trade counts."""

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc).date().isoformat()


def can_open_session_trade(
    state: TradeState,
    timestamp: datetime,
    max_session_trades: int = 2,
) -> bool:
    """Return whether this session remains below the configured signal cap."""

    session = active_session(timestamp)
    if session is None:
        return False
    day = session_key(timestamp)
    return state.session_trade_counts.get(day, {}).get(session, 0) < max_session_trades


def record_session_trade(state: TradeState, timestamp: datetime) -> TradeState:
    """Increment the active session's generated setup count."""

    session = active_session(timestamp)
    if session is None:
        return state
    day = session_key(timestamp)
    state.session_trade_counts.setdefault(day, {})
    state.session_trade_counts[day][session] = state.session_trade_counts[day].get(session, 0) + 1
    return state


def evaluate_xauusd_scalp(
    m5_candles: Iterable[Candle],
    m15_candles: Iterable[Candle],
    h1_candles: Iterable[Candle],
    *,
    state: TradeState | None = None,
    config: StrategyConfig | None = None,
    now: datetime | None = None,
) -> str:
    """Return one valid setup or the strict no-trade response."""

    cfg = config or StrategyConfig()
    m5 = sorted(list(m5_candles), key=lambda candle: candle.time)
    m15 = sorted(list(m15_candles), key=lambda candle: candle.time)
    h1 = sorted(list(h1_candles), key=lambda candle: candle.time)

    if len(m5) < 60 or len(m15) < 50 or len(h1) < 50:
        return NO_TRADE

    signal_time = now or m5[-1].time
    if active_session(signal_time) is None:
        return NO_TRADE

    if state is not None and not can_open_session_trade(
        state,
        signal_time,
        max_session_trades=cfg.max_session_trades,
    ):
        return NO_TRADE

    htf_bias = _higher_timeframe_bias(m15, h1)
    if htf_bias is None:
        return NO_TRADE

    if _m5_trend(m5) != htf_bias:
        return NO_TRADE

    direction: Direction = "Buy" if htf_bias == "Bullish" else "Sell"
    setup = _build_candidate(m5, htf_bias, direction, cfg)
    if setup is None:
        return NO_TRADE
    return setup.format()


def analyze_market(
    m5: Iterable[Candle],
    m15: Iterable[Candle],
    h1: Iterable[Candle],
    *,
    now: datetime | None = None,
    trade_state: TradeState | dict[str, dict[str, int]] | None = None,
    max_trades_per_session: int = 2,
) -> str:
    """Compatibility wrapper around :func:`evaluate_xauusd_scalp`."""

    state: TradeState | None
    if isinstance(trade_state, TradeState) or trade_state is None:
        state = trade_state
    else:
        state = TradeState(session_trade_counts=trade_state)
    return evaluate_xauusd_scalp(
        m5,
        m15,
        h1,
        state=state,
        config=StrategyConfig(max_session_trades=max_trades_per_session),
        now=now,
    )


def _build_candidate(
    candles: list[Candle],
    bias: Bias,
    direction: Direction,
    config: StrategyConfig,
) -> TradeSetup | None:
    sweep = _detect_liquidity_sweep(candles, direction, config)
    if sweep is None:
        return None

    displacement = _is_displacement(candles, config)
    if not _has_candle_confirmation(candles, sweep, displacement):
        return None

    if not _has_bos_or_choch(candles, sweep, config):
        return None

    order_block = _find_order_block(candles, sweep, config)
    if order_block is None:
        return None

    fvg = _find_fvg(candles, direction)
    if fvg is None:
        return None

    indicators = _indicator_filters(candles, direction, displacement, config)
    if indicators is None:
        return None
    latest_rsi, latest_adx = indicators

    average_range = _average_range(candles[-21:-1])
    if average_range < config.min_average_range:
        return None

    entry = round(candles[-1].close, 2)
    buffer = max(config.structure_buffer, average_range * 0.10)
    if direction == "Buy":
        stop_loss = round(min(sweep.extreme, order_block.low) - buffer, 2)
        risk = entry - stop_loss
        if risk <= 0:
            return None
        take_profit_1 = round(entry + risk, 2)
        take_profit_2 = round(entry + risk * 2.0, 2)
        setup_type = "Buy after sell-side liquidity sweep into demand OB/FVG"
    else:
        stop_loss = round(max(sweep.extreme, order_block.high) + buffer, 2)
        risk = stop_loss - entry
        if risk <= 0:
            return None
        take_profit_1 = round(entry - risk, 2)
        take_profit_2 = round(entry - risk * 2.0, 2)
        setup_type = "Sell after buy-side liquidity sweep into supply OB/FVG"

    risk_reward = _risk_reward(entry, stop_loss, take_profit_2, direction)
    if risk_reward + 1e-9 < config.min_risk_reward:
        return None

    score = _score_setup(candles[-1], order_block, fvg, latest_adx, displacement, config)
    if score < 7:
        return None

    confirmation = (
        f"{sweep.liquidity_side} liquidity sweep at {sweep.extreme:.2f}, "
        f"strong {'displacement' if displacement else 'engulfing'} confirmation, "
        f"and reclaim of {sweep.level:.2f}."
    )
    reasoning = (
        f"M15/H1 {bias.lower()} bias with M5 BOS/CHoCH; EMA20/EMA50 aligned, "
        f"RSI {latest_rsi:.1f}, ADX {latest_adx:.1f}; "
        f"{order_block.kind} {order_block.low:.2f}-{order_block.high:.2f} and "
        f"{fvg.kind} {fvg.low:.2f}-{fvg.high:.2f}. "
        "At TP1 close 50% and move SL to breakeven; let TP2 run only if momentum continues."
    )

    return TradeSetup(
        trade_type=direction,
        market_bias=bias,
        setup_type=setup_type,
        entry=entry,
        stop_loss=stop_loss,
        take_profit_1=take_profit_1,
        take_profit_2=take_profit_2,
        risk_reward=risk_reward,
        score=score,
        confirmation=confirmation,
        reasoning=reasoning,
    )


def _higher_timeframe_bias(m15: list[Candle], h1: list[Candle]) -> Bias | None:
    m15_bias = _timeframe_bias(m15)
    h1_bias = _timeframe_bias(h1)
    if m15_bias is not None and m15_bias == h1_bias:
        return m15_bias
    return None


def _m5_trend(candles: list[Candle]) -> Bias | None:
    return _timeframe_bias(candles)


def _timeframe_bias(candles: list[Candle]) -> Bias | None:
    if len(candles) < 50:
        return None
    closes = [candle.close for candle in candles]
    ema20 = _ema(closes, 20)[-1]
    ema50 = _ema(closes, 50)[-1]
    recent = candles[-12:]
    previous = candles[-28:-12]
    if not previous:
        return None

    broke_high = max(candle.high for candle in recent) > max(candle.high for candle in previous)
    broke_low = min(candle.low for candle in recent) < min(candle.low for candle in previous)
    latest_close = closes[-1]
    if ema20 > ema50 and latest_close > ema20 and broke_high:
        return "Bullish"
    if ema20 < ema50 and latest_close < ema20 and broke_low:
        return "Bearish"
    return None


def _detect_liquidity_sweep(
    candles: list[Candle],
    direction: Direction,
    config: StrategyConfig,
) -> Sweep | None:
    if len(candles) < 35:
        return None

    start = max(18, len(candles) - config.sweep_scan_candles - 1)
    end = len(candles) - 1
    for index in reversed(range(start, end)):
        prior = candles[max(0, index - 30) : index]
        if len(prior) < 12:
            continue
        candle = candles[index]
        if direction == "Buy":
            equal_low = _swept_equal_level(candle, prior, "low", config)
            if equal_low is None:
                continue
            return Sweep(
                direction=direction,
                index=index,
                level=equal_low,
                extreme=candle.low,
                liquidity_side="Sell-side",
            )
        else:
            equal_high = _swept_equal_level(candle, prior, "high", config)
            if equal_high is None:
                continue
            return Sweep(
                direction=direction,
                index=index,
                level=equal_high,
                extreme=candle.high,
                liquidity_side="Buy-side",
            )
    return None


def _swept_equal_level(
    sweep_candle: Candle,
    prior: list[Candle],
    side: Literal["high", "low"],
    config: StrategyConfig,
) -> float | None:
    levels = _equal_levels(prior, side, config.equal_level_tolerance)
    if side == "low":
        swept = [
            level
            for level in levels
            if sweep_candle.low < level - config.sweep_break_buffer and sweep_candle.close > level
        ]
        return max(swept) if swept else None

    swept = [
        level
        for level in levels
        if sweep_candle.high > level + config.sweep_break_buffer and sweep_candle.close < level
    ]
    return min(swept) if swept else None


def _equal_levels(
    candles: list[Candle],
    side: Literal["high", "low"],
    tolerance: float,
) -> list[float]:
    levels = [candle.high if side == "high" else candle.low for candle in candles]
    matches: list[float] = []
    for index in range(len(levels) - 1, 0, -1):
        level = levels[index]
        for other in reversed(levels[:index]):
            if abs(level - other) <= tolerance:
                matches.append((level + other) / 2)
    return matches


def _has_candle_confirmation(candles: list[Candle], sweep: Sweep, displacement: bool) -> bool:
    if sweep.index != len(candles) - 2:
        return False

    current = candles[-1]
    previous = candles[-2]
    sweep_candle = candles[sweep.index]
    if sweep.direction == "Buy":
        rejection = sweep_candle.close > sweep.level
        engulfing = current.bullish and previous.bearish and current.close >= previous.open
        impulse = current.bullish and displacement and current.close > previous.high
        reclaimed = current.close > sweep.level and current.close > previous.high
    else:
        rejection = sweep_candle.close < sweep.level
        engulfing = current.bearish and previous.bullish and current.close <= previous.open
        impulse = current.bearish and displacement and current.close < previous.low
        reclaimed = current.close < sweep.level and current.close < previous.low
    return rejection and reclaimed and (engulfing or impulse)


def _has_bos_or_choch(candles: list[Candle], sweep: Sweep, config: StrategyConfig) -> bool:
    current = candles[-1]
    structure_start = max(0, sweep.index - config.structure_lookback)
    structure = candles[structure_start : sweep.index + 1]
    if len(structure) < 5:
        return False
    if sweep.direction == "Buy":
        return current.close > max(candle.high for candle in structure)
    return current.close < min(candle.low for candle in structure)


def _find_order_block(candles: list[Candle], sweep: Sweep, config: StrategyConfig) -> Zone | None:
    start = max(1, sweep.index - config.structure_lookback)
    for index in range(len(candles) - 2, start - 1, -1):
        candidate = candles[index]
        next_candle = candles[index + 1]
        local_average = _average_range(candles[max(0, index - 14) : index + 1])
        displaced = local_average > 0 and next_candle.range >= local_average * config.impulse_range_multiplier
        if sweep.direction == "Buy" and candidate.bearish and next_candle.bullish and displaced:
            return Zone("Demand OB", low=candidate.low, high=max(candidate.open, candidate.close))
        if sweep.direction == "Sell" and candidate.bullish and next_candle.bearish and displaced:
            return Zone("Supply OB", low=min(candidate.open, candidate.close), high=candidate.high)
    return None


def _find_fvg(candles: list[Candle], direction: Direction) -> Zone | None:
    if len(candles) < 3:
        return None
    for index in range(len(candles) - 1, max(1, len(candles) - 18), -1):
        first = candles[index - 2]
        third = candles[index]
        if direction == "Buy" and third.low > first.high:
            return Zone("Bullish FVG", low=first.high, high=third.low)
        if direction == "Sell" and third.high < first.low:
            return Zone("Bearish FVG", low=third.high, high=first.low)
    return None


def _indicator_filters(
    candles: list[Candle],
    direction: Direction,
    displacement: bool,
    config: StrategyConfig,
) -> tuple[float, float] | None:
    closes = [candle.close for candle in candles]
    ema20 = _ema(closes, 20)[-1]
    ema50 = _ema(closes, 50)[-1]
    latest_rsi = _rsi(closes, 14)
    latest_adx = _adx(candles, 14)
    if latest_adx <= config.min_adx and not displacement:
        return None

    if direction == "Buy":
        if not (ema20 > ema50 and closes[-1] > ema20):
            return None
        if not (config.buy_rsi_floor <= latest_rsi <= config.buy_rsi_ceiling):
            return None
    else:
        if not (ema20 < ema50 and closes[-1] < ema20):
            return None
        if not (config.sell_rsi_floor <= latest_rsi <= config.sell_rsi_ceiling):
            return None
    return latest_rsi, latest_adx


def _score_setup(
    candle: Candle,
    order_block: Zone,
    fvg: Zone,
    latest_adx: float,
    displacement: bool,
    config: StrategyConfig,
) -> int:
    score = 7
    if latest_adx > config.min_adx + 5:
        score += 1
    if displacement:
        score += 1
    if order_block.contains(candle.close) or fvg.contains(candle.close):
        score += 1
    return min(score, 10)


def _risk_reward(entry: float, stop_loss: float, take_profit: float, direction: Direction) -> float:
    risk = abs(entry - stop_loss)
    if risk <= 0:
        return 0.0
    reward = take_profit - entry if direction == "Buy" else entry - take_profit
    return reward / risk


def _average_range(candles: list[Candle]) -> float:
    if not candles:
        return 0.0
    return sum(candle.range for candle in candles) / len(candles)


def _is_displacement(candles: list[Candle], config: StrategyConfig) -> bool:
    if len(candles) < 21:
        return False
    current = candles[-1]
    prior_average = _average_range(candles[-21:-1])
    if prior_average <= 0 or current.range <= 0:
        return False
    return (
        current.range >= prior_average * config.impulse_range_multiplier
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
        gains.append(max(change, 0.0))
        losses.append(abs(min(change, 0.0)))
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
