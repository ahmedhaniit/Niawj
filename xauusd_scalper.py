"""Rule-based XAUUSD M5 scalping setup generator.

The analyzer intentionally fails closed: a setup is emitted only when every
institutional-trading condition is present. Otherwise it returns the exact
no-trade response required by the trading prompt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Mapping, Sequence


NO_TRADE = "No trade \u2013 conditions not met"


class Direction(str, Enum):
    BUY = "Buy"
    SELL = "Sell"


class Bias(str, Enum):
    BULLISH = "Bullish"
    BEARISH = "Bearish"


class Session(str, Enum):
    LONDON = "London"
    NEW_YORK = "New York"
    OTHER = "Other"


class StructureEvent(str, Enum):
    BOS = "BOS"
    CHOCH = "CHoCH"


class LiquiditySide(str, Enum):
    BUY_SIDE = "buy-side"
    SELL_SIDE = "sell-side"


class CandleConfirmation(str, Enum):
    ENGULFING = "engulfing"
    IMPULSE = "impulse"


@dataclass(frozen=True)
class HigherTimeframeContext:
    """M15/H1 context used to establish directional permission."""

    bias: Bias
    key_liquidity_zones: Sequence[str]
    major_structure: StructureEvent


@dataclass(frozen=True)
class M5Structure:
    """Intraday M5 structure and momentum state."""

    trend: Bias
    event: StructureEvent
    momentum_shift: bool


@dataclass(frozen=True)
class LiquidityContext:
    """Smart-money liquidity state for the candidate direction."""

    equal_highs: bool
    equal_lows: bool
    liquidity_sweep: bool
    swept_side: LiquiditySide
    buy_side_liquidity: Sequence[str]
    sell_side_liquidity: Sequence[str]


@dataclass(frozen=True)
class KeyZones:
    """Required institutional zones around the proposed entry."""

    supply_zone: tuple[float, float] | None
    demand_zone: tuple[float, float] | None
    order_block: tuple[float, float] | None
    fair_value_gap: tuple[float, float] | None


@dataclass(frozen=True)
class Indicators:
    """Indicator confirmation for the proposed trade."""

    ema20: float
    ema50: float
    rsi: float
    adx: float
    strong_displacement_candle: bool


@dataclass(frozen=True)
class EntryConfirmation:
    """Mandatory entry trigger evidence."""

    liquidity_sweep: bool
    strong_rejection: bool
    displacement: bool
    candle_confirmation: CandleConfirmation | None
    key_level_reclaimed: bool


@dataclass(frozen=True)
class TradeCandidate:
    """A possible M5 setup before strict validation."""

    direction: Direction
    entry: tuple[float, float]
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    score: int
    setup_type: str
    confirmation: EntryConfirmation
    reason: str
    stop_loss_based_on_structure: bool = True


@dataclass(frozen=True)
class MarketSnapshot:
    """All market inputs needed for one five-minute execution."""

    session: Session
    session_trade_counts: Mapping[Session, int] = field(default_factory=dict)
    high_timeframe: HigherTimeframeContext | None = None
    m5_structure: M5Structure | None = None
    liquidity: LiquidityContext | None = None
    key_zones: KeyZones | None = None
    indicators: Indicators | None = None
    low_volatility: bool = False
    choppy_conditions: bool = False
    candidates: Sequence[TradeCandidate] = field(default_factory=tuple)


class TradeSetupAnalyzer:
    """Generate one high-probability XAUUSD M5 setup, or no trade."""

    max_trades_per_session = 2
    minimum_reward_to_risk = 2.0
    minimum_score = 7
    maximum_entry_range = 1.0
    minimum_adx = 20.0

    def analyze(self, snapshot: MarketSnapshot) -> str:
        if not self._market_allows_trading(snapshot):
            return NO_TRADE

        valid_candidates = [
            candidate
            for candidate in snapshot.candidates
            if self._candidate_is_valid(snapshot, candidate)
        ]
        if not valid_candidates:
            return NO_TRADE

        selected = max(valid_candidates, key=lambda candidate: candidate.score)
        return self._format_setup(snapshot, selected)

    def _market_allows_trading(self, snapshot: MarketSnapshot) -> bool:
        if snapshot.session not in {Session.LONDON, Session.NEW_YORK}:
            return False
        if snapshot.session_trade_counts.get(snapshot.session, 0) >= self.max_trades_per_session:
            return False
        if snapshot.low_volatility or snapshot.choppy_conditions:
            return False
        if not all(
            [
                snapshot.high_timeframe,
                snapshot.m5_structure,
                snapshot.liquidity,
                snapshot.key_zones,
                snapshot.indicators,
            ]
        ):
            return False
        assert snapshot.high_timeframe is not None
        assert snapshot.m5_structure is not None
        assert snapshot.liquidity is not None
        return (
            bool(snapshot.high_timeframe.key_liquidity_zones)
            and snapshot.high_timeframe.major_structure
            in {StructureEvent.BOS, StructureEvent.CHOCH}
            and snapshot.m5_structure.event in {StructureEvent.BOS, StructureEvent.CHOCH}
            and snapshot.m5_structure.momentum_shift
            and snapshot.liquidity.liquidity_sweep
            and bool(snapshot.liquidity.buy_side_liquidity)
            and bool(snapshot.liquidity.sell_side_liquidity)
        )

    def _candidate_is_valid(
        self, snapshot: MarketSnapshot, candidate: TradeCandidate
    ) -> bool:
        assert snapshot.high_timeframe is not None
        assert snapshot.m5_structure is not None
        assert snapshot.key_zones is not None
        assert snapshot.indicators is not None

        return all(
            [
                self._direction_matches_bias(snapshot, candidate.direction),
                self._entry_range_is_precise(candidate),
                self._liquidity_matches_direction(snapshot, candidate.direction),
                self._zones_are_valid(snapshot.key_zones, candidate.direction),
                self._indicators_confirm(snapshot.indicators, candidate.direction),
                self._risk_reward_is_valid(candidate),
                candidate.score >= self.minimum_score,
                candidate.stop_loss_based_on_structure,
                self._entry_confirmation_is_valid(candidate.confirmation),
            ]
        )

    def _direction_matches_bias(
        self, snapshot: MarketSnapshot, direction: Direction
    ) -> bool:
        expected = Bias.BULLISH if direction == Direction.BUY else Bias.BEARISH
        return (
            snapshot.high_timeframe is not None
            and snapshot.m5_structure is not None
            and snapshot.high_timeframe.bias == expected
            and snapshot.m5_structure.trend == expected
        )

    def _liquidity_matches_direction(
        self, snapshot: MarketSnapshot, direction: Direction
    ) -> bool:
        assert snapshot.liquidity is not None
        if direction == Direction.BUY:
            return (
                snapshot.liquidity.swept_side == LiquiditySide.SELL_SIDE
                and snapshot.liquidity.equal_lows
            )
        return (
            snapshot.liquidity.swept_side == LiquiditySide.BUY_SIDE
            and snapshot.liquidity.equal_highs
        )

    def _entry_range_is_precise(self, candidate: TradeCandidate) -> bool:
        lower, upper = sorted(candidate.entry)
        return upper - lower <= self.maximum_entry_range

    def _zones_are_valid(self, zones: KeyZones, direction: Direction) -> bool:
        return (
            zones.supply_zone is not None
            and zones.demand_zone is not None
            and zones.order_block is not None
            and zones.fair_value_gap is not None
            and self._zone_is_ordered(zones.supply_zone)
            and self._zone_is_ordered(zones.demand_zone)
            and self._zone_is_ordered(zones.order_block)
            and self._zone_is_ordered(zones.fair_value_gap)
        )

    def _zone_is_ordered(self, zone: tuple[float, float]) -> bool:
        return zone[0] <= zone[1]

    def _indicators_confirm(self, indicators: Indicators, direction: Direction) -> bool:
        ema_aligned = (
            indicators.ema20 > indicators.ema50
            if direction == Direction.BUY
            else indicators.ema20 < indicators.ema50
        )
        rsi_not_overextended = (
            30.0 < indicators.rsi < 70.0
            if direction == Direction.BUY
            else 30.0 < indicators.rsi < 70.0
        )
        volatility_confirmed = (
            indicators.adx > self.minimum_adx or indicators.strong_displacement_candle
        )
        return ema_aligned and rsi_not_overextended and volatility_confirmed

    def _risk_reward_is_valid(self, candidate: TradeCandidate) -> bool:
        risk = self._risk(candidate)
        reward = self._reward(candidate)
        return risk > 0 and reward / risk >= self.minimum_reward_to_risk

    def _entry_confirmation_is_valid(self, confirmation: EntryConfirmation) -> bool:
        return (
            confirmation.liquidity_sweep
            and (confirmation.strong_rejection or confirmation.displacement)
            and confirmation.candle_confirmation
            in {CandleConfirmation.ENGULFING, CandleConfirmation.IMPULSE}
            and confirmation.key_level_reclaimed
        )

    def _format_setup(self, snapshot: MarketSnapshot, candidate: TradeCandidate) -> str:
        assert snapshot.high_timeframe is not None
        risk_reward = self._reward(candidate) / self._risk(candidate)
        return "\n".join(
            [
                f"Market Bias: {snapshot.high_timeframe.bias.value}",
                f"Setup Type: {candidate.setup_type}",
                f"Entry: {self._format_entry(candidate.entry)}",
                f"Stop Loss: {candidate.stop_loss:.2f}",
                (
                    "Take Profits: "
                    f"TP1 {candidate.take_profit_1:.2f}, "
                    f"TP2 {candidate.take_profit_2:.2f}"
                ),
                f"Risk/Reward: 1:{risk_reward:.2f}",
                f"Score: {candidate.score}/10",
                f"Confirmation: {self._confirmation_text(candidate.confirmation)}",
                f"Reasoning: {candidate.reason}",
            ]
        )

    def _format_entry(self, entry: tuple[float, float]) -> str:
        lower, upper = sorted(entry)
        if lower == upper:
            return f"{lower:.2f}"
        return f"{lower:.2f}-{upper:.2f}"

    def _confirmation_text(self, confirmation: EntryConfirmation) -> str:
        trigger = "strong rejection" if confirmation.strong_rejection else "displacement"
        candle = confirmation.candle_confirmation.value
        return f"liquidity sweep + {trigger}, {candle} candle, key level reclaimed"

    def _risk(self, candidate: TradeCandidate) -> float:
        entry = self._midpoint(candidate.entry)
        if candidate.direction == Direction.BUY:
            return entry - candidate.stop_loss
        return candidate.stop_loss - entry

    def _reward(self, candidate: TradeCandidate) -> float:
        entry = self._midpoint(candidate.entry)
        if candidate.direction == Direction.BUY:
            return candidate.take_profit_2 - entry
        return entry - candidate.take_profit_2

    def _midpoint(self, price_range: tuple[float, float]) -> float:
        lower, upper = sorted(price_range)
        return (lower + upper) / 2.0


def generate_trade_setup(snapshot: MarketSnapshot) -> str:
    """Convenience wrapper for one five-minute automation execution."""

    return TradeSetupAnalyzer().analyze(snapshot)


def first_setup_or_no_trade(snapshots: Iterable[MarketSnapshot]) -> str:
    """Return the first valid setup from a stream of five-minute snapshots."""

    analyzer = TradeSetupAnalyzer()
    for snapshot in snapshots:
        result = analyzer.analyze(snapshot)
        if result != NO_TRADE:
            return result
    return NO_TRADE
