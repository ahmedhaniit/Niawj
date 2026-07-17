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
StructureKind = Literal["BOS", "CHoCH"]


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
    candle_index: int

    def contains(self, price: float) -> bool:
        return self.low <= price <= self.high

    def overlaps(self, low: float, high: float) -> bool:
        return self.low <= high and low <= self.high


@dataclass(frozen=True)
class Sweep:
    """Liquidity sweep details used by entry confirmation."""

    direction: Direction
    index: int
    level: float
    extreme: float
    liquidity_side: str


@dataclass(frozen=True)
class StructureBreak:
    """A close-confirmed break of a prior price structure."""

    kind: StructureKind
    direction: Bias
    level: float


@dataclass(frozen=True)
class TimeframeContext:
    """Directional structure and liquidity boundaries for one timeframe."""

    bias: Bias
    structure: StructureBreak
    sell_side_liquidity: float
    buy_side_liquidity: float


@dataclass
class TradeState:
    """Per-day, per-session generated setup counts.

    The evaluator is pure apart from reading this state; callers should call
    :func:`record_session_trade` after executing or recording a non-no-trade
    setup.
    """

    session_trade_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    last_signal_candles: dict[str, dict[str, str]] = field(default_factory=dict)

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
    min_rejection_wick_fraction: float = 0.25
    momentum_body_multiplier: float = 1.25
    min_fvg_size: float = 0.10
    max_data_age_minutes: float = 6.0

    def __post_init__(self) -> None:
        if not 1 <= self.max_session_trades <= 2:
            raise ValueError("max_session_trades must be one or two")
        if self.min_risk_reward < 2.0:
            raise ValueError("min_risk_reward cannot be below 2.0")
        if self.min_adx < 20.0:
            raise ValueError("min_adx cannot be below 20")


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

    if "session_trade_counts" in data:
        counts = data.get("session_trade_counts")
        last_signals = data.get("last_signal_candles", {})
        if not isinstance(counts, dict) or not isinstance(last_signals, dict):
            raise ValueError("Trade state fields must be JSON objects")
        return TradeState(
            session_trade_counts={
                str(day): {str(session): int(count) for session, count in sessions.items()}
                for day, sessions in counts.items()
            },
            last_signal_candles={
                str(day): {str(session): str(value) for session, value in sessions.items()}
                for day, sessions in last_signals.items()
            },
        )

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
    """Persist per-session trade counts with an atomic file replacement."""

    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = state_path.with_name(f".{state_path.name}.tmp")
    with temporary_path.open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "session_trade_counts": state.session_trade_counts,
                "last_signal_candles": state.last_signal_candles,
            },
            handle,
            indent=2,
            sort_keys=True,
        )
        handle.write("\n")
    temporary_path.replace(state_path)


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


def has_recorded_signal(
    state: TradeState,
    timestamp: datetime,
    candle_time: datetime,
) -> bool:
    """Return whether this candle already emitted a setup in the active session."""

    session = active_session(timestamp)
    if session is None:
        return True
    day = session_key(timestamp)
    normalized = _normalize_datetime(candle_time).isoformat()
    return state.last_signal_candles.get(day, {}).get(session) == normalized


def record_session_trade(
    state: TradeState,
    timestamp: datetime,
    candle_time: datetime | None = None,
) -> TradeState:
    """Increment the active session's generated setup count."""

    session = active_session(timestamp)
    if session is None:
        return state
    day = session_key(timestamp)
    state.session_trade_counts.setdefault(day, {})
    state.session_trade_counts[day][session] = state.session_trade_counts[day].get(session, 0) + 1
    state.last_signal_candles.setdefault(day, {})
    state.last_signal_candles[day][session] = _normalize_datetime(candle_time or timestamp).isoformat()
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

    # A persisted state object is mandatory. Without it, the two-trade session
    # cap cannot be guaranteed across scheduled executions.
    if state is None or not can_open_session_trade(
        state,
        signal_time,
        max_session_trades=cfg.max_session_trades,
    ):
        return NO_TRADE

    if has_recorded_signal(state, signal_time, m5[-1].time):
        return NO_TRADE

    if not _is_fresh(m5[-1].time, signal_time, cfg.max_data_age_minutes):
        return NO_TRADE

    htf_context = _higher_timeframe_context(m15, h1)
    if htf_context is None:
        return NO_TRADE

    m15_context, h1_context = htf_context
    m5_context = _timeframe_context(m5)
    if m5_context is None or m5_context.bias != m15_context.bias:
        return NO_TRADE

    direction: Direction = "Buy" if m15_context.bias == "Bullish" else "Sell"
    setup = _build_candidate(
        m5,
        m15_context,
        h1_context,
        m5_context,
        direction,
        cfg,
    )
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
    m15_context: TimeframeContext,
    h1_context: TimeframeContext,
    m5_context: TimeframeContext,
    direction: Direction,
    config: StrategyConfig,
) -> TradeSetup | None:
    sweep = _detect_liquidity_sweep(candles, direction, config)
    if sweep is None:
        return None

    displacement = _is_displacement(candles, config)
    confirmation_type = _candle_confirmation(candles, sweep, displacement, config)
    if confirmation_type is None:
        return None

    entry_structure = _entry_structure_break(candles, sweep, config)
    if entry_structure is None:
        return None

    order_block = _find_order_block(candles, sweep, config)
    if order_block is None:
        return None

    sweep_candle = candles[sweep.index]
    if not order_block.overlaps(sweep_candle.low, sweep_candle.high):
        return None

    fvg = _find_fvg(candles, direction, since_index=sweep.index, config=config)
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
        setup_type = "Buy – sell-side sweep reversal from demand/order block"
    else:
        stop_loss = round(max(sweep.extreme, order_block.high) + buffer, 2)
        risk = stop_loss - entry
        if risk <= 0:
            return None
        take_profit_1 = round(entry - risk, 2)
        take_profit_2 = round(entry - risk * 2.0, 2)
        setup_type = "Sell – buy-side sweep reversal from supply/order block"

    risk_reward = _risk_reward(entry, stop_loss, take_profit_2, direction)
    if risk_reward + 1e-9 < config.min_risk_reward:
        return None

    score = _score_setup(candles[-1], order_block, fvg, latest_adx, displacement, config)
    if score < 7:
        return None

    confirmation = (
        f"{sweep.liquidity_side} liquidity sweep at {sweep.extreme:.2f}, "
        f"strong rejection plus {confirmation_type}, and reclaim of {sweep.level:.2f}."
    )
    bias = m15_context.bias
    reasoning = (
        f"M15 {m15_context.structure.kind} {m15_context.structure.level:.2f} and "
        f"H1 {h1_context.structure.kind} {h1_context.structure.level:.2f} confirm "
        f"{bias.lower()} bias; M5 {entry_structure.kind} {entry_structure.level:.2f} "
        f"with momentum shift. HTF liquidity: sell-side "
        f"{min(m15_context.sell_side_liquidity, h1_context.sell_side_liquidity):.2f}, "
        f"buy-side {max(m15_context.buy_side_liquidity, h1_context.buy_side_liquidity):.2f}. "
        f"EMA20/EMA50 aligned, "
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


def _higher_timeframe_context(
    m15: list[Candle],
    h1: list[Candle],
) -> tuple[TimeframeContext, TimeframeContext] | None:
    m15_context = _timeframe_context(m15)
    h1_context = _timeframe_context(h1)
    if (
        m15_context is not None
        and h1_context is not None
        and m15_context.bias == h1_context.bias
    ):
        return m15_context, h1_context
    return None


def _m5_trend(candles: list[Candle]) -> Bias | None:
    context = _timeframe_context(candles)
    return context.bias if context is not None else None


def _timeframe_context(candles: list[Candle]) -> TimeframeContext | None:
    if len(candles) < 50:
        return None
    closes = [candle.close for candle in candles]
    ema20 = _ema(closes, 20)[-1]
    ema50 = _ema(closes, 50)[-1]
    recent = candles[-12:]
    previous = candles[-28:-12]
    if not previous:
        return None

    prior_high = max(candle.high for candle in previous)
    prior_low = min(candle.low for candle in previous)
    broke_high = any(candle.close > prior_high for candle in recent)
    broke_low = any(candle.close < prior_low for candle in recent)
    latest_close = closes[-1]
    if ema20 > ema50 and latest_close > ema20 and broke_high:
        kind: StructureKind = "BOS" if closes[-29] > _ema(closes[:-28], 20)[-1] else "CHoCH"
        return TimeframeContext(
            bias="Bullish",
            structure=StructureBreak(kind, "Bullish", prior_high),
            sell_side_liquidity=min(candle.low for candle in previous),
            buy_side_liquidity=max(candle.high for candle in recent),
        )
    if ema20 < ema50 and latest_close < ema20 and broke_low:
        kind = "BOS" if closes[-29] < _ema(closes[:-28], 20)[-1] else "CHoCH"
        return TimeframeContext(
            bias="Bearish",
            structure=StructureBreak(kind, "Bearish", prior_low),
            sell_side_liquidity=min(candle.low for candle in recent),
            buy_side_liquidity=max(candle.high for candle in previous),
        )
    return None


def _timeframe_bias(candles: list[Candle]) -> Bias | None:
    """Compatibility helper returning only the directional context."""

    context = _timeframe_context(candles)
    return context.bias if context is not None else None


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


def _candle_confirmation(
    candles: list[Candle],
    sweep: Sweep,
    displacement: bool,
    config: StrategyConfig,
) -> str | None:
    if sweep.index != len(candles) - 2:
        return None

    current = candles[-1]
    previous = candles[-2]
    sweep_candle = candles[sweep.index]
    if sweep_candle.range <= 0:
        return None

    prior_bodies = [candle.body for candle in candles[max(0, sweep.index - 5) : sweep.index]]
    average_body = sum(prior_bodies) / len(prior_bodies) if prior_bodies else 0.0
    momentum_shift = average_body > 0 and current.body >= average_body * config.momentum_body_multiplier

    if sweep.direction == "Buy":
        rejection_wick = min(sweep_candle.open, sweep_candle.close) - sweep_candle.low
        rejection = (
            sweep_candle.close > sweep.level
            and rejection_wick / sweep_candle.range >= config.min_rejection_wick_fraction
        )
        engulfing = (
            current.bullish
            and previous.bearish
            and current.open <= previous.close
            and current.close >= previous.open
        )
        impulse = current.bullish and displacement and current.close > previous.high
        reclaimed = current.close > sweep.level and current.close > previous.high
    else:
        rejection_wick = sweep_candle.high - max(sweep_candle.open, sweep_candle.close)
        rejection = (
            sweep_candle.close < sweep.level
            and rejection_wick / sweep_candle.range >= config.min_rejection_wick_fraction
        )
        engulfing = (
            current.bearish
            and previous.bullish
            and current.open >= previous.close
            and current.close <= previous.open
        )
        impulse = current.bearish and displacement and current.close < previous.low
        reclaimed = current.close < sweep.level and current.close < previous.low
    if not (rejection and reclaimed and momentum_shift and (engulfing or impulse)):
        return None
    if impulse and engulfing:
        return "engulfing displacement"
    return "displacement impulse" if impulse else "engulfing candle"


def _has_candle_confirmation(candles: list[Candle], sweep: Sweep, displacement: bool) -> bool:
    """Compatibility wrapper for callers using the former boolean helper."""

    return _candle_confirmation(candles, sweep, displacement, StrategyConfig()) is not None


def _entry_structure_break(
    candles: list[Candle],
    sweep: Sweep,
    config: StrategyConfig,
) -> StructureBreak | None:
    current = candles[-1]
    structure_start = max(0, sweep.index - config.structure_lookback)
    structure = candles[structure_start:sweep.index]
    if len(structure) < 5:
        return None
    if sweep.direction == "Buy":
        level = max(candle.high for candle in structure)
        if current.close > level:
            prior_bias = _short_term_bias(structure)
            return StructureBreak("BOS" if prior_bias == "Bullish" else "CHoCH", "Bullish", level)
        return None
    level = min(candle.low for candle in structure)
    if current.close < level:
        prior_bias = _short_term_bias(structure)
        return StructureBreak("BOS" if prior_bias == "Bearish" else "CHoCH", "Bearish", level)
    return None


def _has_bos_or_choch(candles: list[Candle], sweep: Sweep, config: StrategyConfig) -> bool:
    """Compatibility wrapper around close-confirmed structure classification."""

    return _entry_structure_break(candles, sweep, config) is not None


def _short_term_bias(candles: list[Candle]) -> Bias | None:
    if len(candles) < 5:
        return None
    midpoint = max(2, len(candles) // 2)
    older = candles[:midpoint]
    newer = candles[midpoint:]
    if not newer:
        return None
    if (
        max(candle.high for candle in newer) > max(candle.high for candle in older)
        and min(candle.low for candle in newer) > min(candle.low for candle in older)
    ):
        return "Bullish"
    if (
        max(candle.high for candle in newer) < max(candle.high for candle in older)
        and min(candle.low for candle in newer) < min(candle.low for candle in older)
    ):
        return "Bearish"
    return None


def _find_order_block(candles: list[Candle], sweep: Sweep, config: StrategyConfig) -> Zone | None:
    start = max(1, sweep.index - config.structure_lookback)
    for index in range(len(candles) - 2, start - 1, -1):
        candidate = candles[index]
        next_candle = candles[index + 1]
        local_average = _average_range(candles[max(0, index - 14) : index + 1])
        displaced = local_average > 0 and next_candle.range >= local_average * config.impulse_range_multiplier
        if sweep.direction == "Buy" and candidate.bearish and next_candle.bullish and displaced:
            return Zone(
                "Demand / bullish order block",
                low=candidate.low,
                high=max(candidate.open, candidate.close),
                candle_index=index,
            )
        if sweep.direction == "Sell" and candidate.bullish and next_candle.bearish and displaced:
            return Zone(
                "Supply / bearish order block",
                low=min(candidate.open, candidate.close),
                high=candidate.high,
                candle_index=index,
            )
    return None


def _find_fvg(
    candles: list[Candle],
    direction: Direction,
    *,
    since_index: int = 0,
    config: StrategyConfig | None = None,
) -> Zone | None:
    if len(candles) < 3:
        return None
    cfg = config or StrategyConfig()
    earliest = max(2, len(candles) - 18, since_index + 1)
    for index in range(len(candles) - 1, earliest - 1, -1):
        first = candles[index - 2]
        third = candles[index]
        if direction == "Buy" and third.low - first.high >= cfg.min_fvg_size:
            return Zone("Bullish FVG", low=first.high, high=third.low, candle_index=index)
        if direction == "Sell" and first.low - third.high >= cfg.min_fvg_size:
            return Zone("Bearish FVG", low=third.high, high=first.low, candle_index=index)
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
    changes = [current - previous for previous, current in zip(values, values[1:])]
    gains = [max(change, 0.0) for change in changes]
    losses = [abs(min(change, 0.0)) for change in changes]
    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:]):
        average_gain = ((average_gain * (period - 1)) + gain) / period
        average_loss = ((average_loss * (period - 1)) + loss) / period
    if average_loss == 0:
        return 100.0
    relative_strength = average_gain / average_loss
    return 100 - (100 / (1 + relative_strength))


def _adx(candles: list[Candle], period: int) -> float:
    if len(candles) < period * 2 + 1:
        return 0.0

    true_ranges: list[float] = []
    plus_dm: list[float] = []
    minus_dm: list[float] = []
    for previous, current in zip(candles, candles[1:]):
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

    smoothed_tr = sum(true_ranges[:period])
    smoothed_plus_dm = sum(plus_dm[:period])
    smoothed_minus_dm = sum(minus_dm[:period])
    dx_values: list[float] = []

    def append_dx() -> None:
        if smoothed_tr <= 0:
            dx_values.append(0.0)
            return
        plus_di = 100 * smoothed_plus_dm / smoothed_tr
        minus_di = 100 * smoothed_minus_dm / smoothed_tr
        denominator = plus_di + minus_di
        dx_values.append(0.0 if denominator == 0 else 100 * abs(plus_di - minus_di) / denominator)

    append_dx()
    for true_range, positive_dm, negative_dm in zip(
        true_ranges[period:],
        plus_dm[period:],
        minus_dm[period:],
    ):
        smoothed_tr = smoothed_tr - (smoothed_tr / period) + true_range
        smoothed_plus_dm = smoothed_plus_dm - (smoothed_plus_dm / period) + positive_dm
        smoothed_minus_dm = smoothed_minus_dm - (smoothed_minus_dm / period) + negative_dm
        append_dx()

    if len(dx_values) < period:
        return 0.0
    adx = sum(dx_values[:period]) / period
    for dx in dx_values[period:]:
        adx = ((adx * (period - 1)) + dx) / period
    return adx


def _is_fresh(candle_time: datetime, signal_time: datetime, max_age_minutes: float) -> bool:
    candle_utc = _normalize_datetime(candle_time)
    signal_utc = _normalize_datetime(signal_time)
    age_seconds = (signal_utc - candle_utc).total_seconds()
    return -60 <= age_seconds <= max_age_minutes * 60


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
