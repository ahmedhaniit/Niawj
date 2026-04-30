from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from enum import Enum
from typing import Iterable, Literal


Direction = Literal["Buy", "Sell"]
Bias = Literal["Bullish", "Bearish"]

NO_TRADE_MESSAGE = "No trade – conditions not met"


class SetupType(str, Enum):
    LIQUIDITY_SWEEP_REVERSAL = "Liquidity sweep reversal"
    BREAKER_RETEST = "Breaker retest"
    ORDER_BLOCK_CONTINUATION = "Order block continuation"


@dataclass(frozen=True)
class PriceZone:
    """A bounded price area used for liquidity, supply/demand, OBs, or FVGs."""

    name: str
    low: float
    high: float

    def __post_init__(self) -> None:
        if self.low > self.high:
            raise ValueError(f"{self.name}: low cannot be greater than high")

    @property
    def midpoint(self) -> float:
        return (self.low + self.high) / 2

    @property
    def width(self) -> float:
        return self.high - self.low

    def contains(self, price: float) -> bool:
        return self.low <= price <= self.high


@dataclass(frozen=True)
class CandleSignal:
    engulfing: bool = False
    impulse: bool = False
    strong_rejection: bool = False
    displacement: bool = False

    @property
    def has_confirmation(self) -> bool:
        return (self.engulfing or self.impulse) and (
            self.strong_rejection or self.displacement
        )


@dataclass(frozen=True)
class HigherTimeframeContext:
    bias: Bias
    liquidity_zones: tuple[PriceZone, ...]
    major_structure: Literal["BOS", "CHoCH"]


@dataclass(frozen=True)
class M5Structure:
    intraday_trend: Bias
    structure_event: Literal["BOS", "CHoCH"]
    momentum_shift: bool


@dataclass(frozen=True)
class LiquidityContext:
    equal_highs: tuple[PriceZone, ...] = ()
    equal_lows: tuple[PriceZone, ...] = ()
    buy_side_liquidity: tuple[PriceZone, ...] = ()
    sell_side_liquidity: tuple[PriceZone, ...] = ()
    swept_zone: PriceZone | None = None
    sweep_direction: Literal["buy-side", "sell-side"] | None = None

    @property
    def has_sweep(self) -> bool:
        return self.swept_zone is not None and self.sweep_direction is not None


@dataclass(frozen=True)
class KeyZones:
    supply: tuple[PriceZone, ...] = ()
    demand: tuple[PriceZone, ...] = ()
    order_blocks: tuple[PriceZone, ...] = ()
    fair_value_gaps: tuple[PriceZone, ...] = ()

    def relevant_for(self, direction: Direction) -> tuple[PriceZone, ...]:
        directional_zones = self.demand if direction == "Buy" else self.supply
        return directional_zones + self.order_blocks + self.fair_value_gaps


@dataclass(frozen=True)
class IndicatorContext:
    ema20: float
    ema50: float
    rsi: float
    adx: float
    strong_displacement_candle: bool = False

    def ema_aligned(self, direction: Direction) -> bool:
        if direction == "Buy":
            return self.ema20 > self.ema50
        return self.ema20 < self.ema50

    def rsi_not_overextended(self, direction: Direction) -> bool:
        if direction == "Buy":
            return 35 <= self.rsi <= 68
        return 32 <= self.rsi <= 65

    @property
    def volatility_confirmed(self) -> bool:
        return self.adx > 20 or self.strong_displacement_candle


@dataclass(frozen=True)
class TradeCandidate:
    direction: Direction
    setup_type: SetupType
    entry_low: float
    entry_high: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    candle_signal: CandleSignal
    reclaimed_level: float | None
    score: int
    reason: str

    def __post_init__(self) -> None:
        if self.entry_low > self.entry_high:
            raise ValueError("entry_low cannot be greater than entry_high")
        if self.score < 1 or self.score > 10:
            raise ValueError("score must be between 1 and 10")

    @property
    def entry(self) -> float:
        return round((self.entry_low + self.entry_high) / 2, 2)

    @property
    def entry_range_width(self) -> float:
        return self.entry_high - self.entry_low

    @property
    def risk(self) -> float:
        if self.direction == "Buy":
            return self.entry - self.stop_loss
        return self.stop_loss - self.entry

    @property
    def reward_to_tp2(self) -> float:
        if self.direction == "Buy":
            return self.take_profit_2 - self.entry
        return self.entry - self.take_profit_2

    @property
    def risk_reward(self) -> float:
        if self.risk <= 0:
            return 0
        return self.reward_to_tp2 / self.risk

    def has_reclaimed_key_level(self) -> bool:
        return self.reclaimed_level is not None


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    timestamp_utc: time
    htf: HigherTimeframeContext
    m5: M5Structure
    liquidity: LiquidityContext
    key_zones: KeyZones
    indicators: IndicatorContext
    candidate: TradeCandidate | None = None
    session_trade_counts: dict[str, int] = field(default_factory=dict)
    low_volatility: bool = False
    choppy: bool = False


def current_session(timestamp_utc: time) -> Literal["London", "New York"] | None:
    """Return the allowed trading session using common UTC gold scalping windows."""

    if time(7, 0) <= timestamp_utc < time(11, 0):
        return "London"
    if time(13, 30) <= timestamp_utc < time(17, 0):
        return "New York"
    return None


def analyze_market(snapshot: MarketSnapshot) -> str:
    """Evaluate a market snapshot and return a single setup or a strict no-trade."""

    candidate = snapshot.candidate
    session = current_session(snapshot.timestamp_utc)
    if candidate is None:
        return NO_TRADE_MESSAGE

    checks = (
        snapshot.symbol.upper() == "XAUUSD",
        session is not None,
        snapshot.session_trade_counts.get(session or "", 0) < 2,
        not snapshot.low_volatility,
        not snapshot.choppy,
        snapshot.htf.bias in ("Bullish", "Bearish"),
        snapshot.htf.major_structure in ("BOS", "CHoCH"),
        snapshot.htf.bias == snapshot.m5.intraday_trend,
        snapshot.m5.structure_event in ("BOS", "CHoCH"),
        snapshot.m5.momentum_shift,
        snapshot.liquidity.has_sweep,
        _has_equal_high_or_low(snapshot.liquidity),
        _sweep_matches_direction(snapshot.liquidity, candidate.direction),
        _has_directional_liquidity(snapshot.liquidity, candidate.direction),
        _has_relevant_key_zone(snapshot.key_zones, candidate),
        snapshot.indicators.ema_aligned(candidate.direction),
        snapshot.indicators.rsi_not_overextended(candidate.direction),
        snapshot.indicators.volatility_confirmed,
        candidate.entry_range_width <= 1,
        candidate.risk_reward >= 2,
        candidate.score >= 7,
        candidate.candle_signal.has_confirmation,
        candidate.has_reclaimed_key_level(),
    )

    if not all(checks):
        return NO_TRADE_MESSAGE

    return _format_setup(snapshot, candidate)


def _sweep_matches_direction(
    liquidity: LiquidityContext, direction: Direction
) -> bool:
    if direction == "Buy":
        return liquidity.sweep_direction == "sell-side"
    return liquidity.sweep_direction == "buy-side"


def _has_equal_high_or_low(liquidity: LiquidityContext) -> bool:
    return bool(liquidity.equal_highs or liquidity.equal_lows)


def _has_directional_liquidity(
    liquidity: LiquidityContext, direction: Direction
) -> bool:
    if direction == "Buy":
        return bool(liquidity.sell_side_liquidity)
    return bool(liquidity.buy_side_liquidity)


def _has_relevant_key_zone(key_zones: KeyZones, candidate: TradeCandidate) -> bool:
    entry = candidate.entry
    return any(zone.contains(entry) for zone in key_zones.relevant_for(candidate.direction))


def _format_setup(snapshot: MarketSnapshot, candidate: TradeCandidate) -> str:
    confirmations = _confirmation_parts(snapshot, candidate)
    risk_reward = f"1:{candidate.risk_reward:.2f}".rstrip("0").rstrip(".")
    take_profits = f"TP1 {candidate.take_profit_1:.2f}, TP2 {candidate.take_profit_2:.2f}"

    return "\n".join(
        (
            f"Market Bias: {snapshot.htf.bias}",
            f"Setup Type: {candidate.setup_type.value} {candidate.direction}",
            f"Entry: {candidate.entry_low:.2f}-{candidate.entry_high:.2f}",
            f"Stop Loss: {candidate.stop_loss:.2f}",
            f"Take Profits: {take_profits}",
            f"Risk/Reward: {risk_reward}",
            f"Score: {candidate.score}/10",
            f"Confirmation: {', '.join(confirmations)}",
            f"Reasoning: {candidate.reason} At TP1 close 50% and move SL to breakeven; let TP2 run only while momentum continues.",
        )
    )


def _confirmation_parts(
    snapshot: MarketSnapshot, candidate: TradeCandidate
) -> list[str]:
    parts: list[str] = []
    sweep = snapshot.liquidity.sweep_direction
    swept_zone = snapshot.liquidity.swept_zone
    if sweep and swept_zone:
        parts.append(f"{sweep} liquidity sweep at {swept_zone.low:.2f}-{swept_zone.high:.2f}")
    if candidate.candle_signal.strong_rejection:
        parts.append("strong rejection")
    if candidate.candle_signal.displacement:
        parts.append("displacement")
    if candidate.candle_signal.engulfing:
        parts.append("engulfing candle")
    if candidate.candle_signal.impulse:
        parts.append("impulse candle")
    if candidate.reclaimed_level is not None:
        parts.append(f"reclaim of {candidate.reclaimed_level:.2f}")
    return parts


def first_valid_setup(snapshots: Iterable[MarketSnapshot]) -> str:
    """Return one valid setup from a batch, otherwise the strict no-trade message."""

    for snapshot in snapshots:
        result = analyze_market(snapshot)
        if result != NO_TRADE_MESSAGE:
            return result
    return NO_TRADE_MESSAGE
