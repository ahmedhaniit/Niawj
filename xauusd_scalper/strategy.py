"""Strict XAUUSD M5 scalping strategy rules.

The engine is intentionally data-source agnostic. Feed it a structured market
snapshot from any provider and it will either return one high-probability setup
or the mandated no-trade response.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


NO_TRADE = "No trade – conditions not met"

ALLOWED_SESSIONS = {"london", "new york", "newyork", "ny"}
VALID_BIASES = {"bullish", "bearish"}
VALID_STRUCTURE_EVENTS = {"bos", "choch"}
VALID_CANDLES = {"engulfing", "impulse"}
STRUCTURE_STOP_TERMS = {"structure", "swing", "order_block", "order block", "liquidity"}


@dataclass(frozen=True)
class EntryRange:
    low: float
    high: float

    @property
    def width(self) -> float:
        return self.high - self.low

    def display(self) -> str:
        if self.low == self.high:
            return format_price(self.low)
        return f"{format_price(self.low)}-{format_price(self.high)}"


@dataclass(frozen=True)
class TradeDecision:
    """Result returned by the strategy evaluator."""

    is_trade: bool
    output: str
    reasons: tuple[str, ...] = field(default_factory=tuple)


def analyze_snapshot(snapshot: Mapping[str, Any]) -> TradeDecision:
    """Evaluate one market snapshot against the strict XAUUSD scalping rules."""

    reasons: list[str] = []

    def reject(reason: str) -> None:
        reasons.append(reason)

    setup = mapping(snapshot.get("setup"))
    trade_type = normalized_text(
        first_present(setup, "type", "trade_type", "setup_type") or snapshot.get("trade_type")
    )

    htf = mapping(first_present(snapshot, "higher_timeframe", "htf"))
    htf_bias = normalized_text(first_present(htf, "bias", "market_bias"))
    expected_type = "buy" if htf_bias == "bullish" else "sell" if htf_bias == "bearish" else ""

    if htf_bias not in VALID_BIASES:
        reject("higher timeframe bias must be Bullish or Bearish")

    if trade_type not in {"buy", "sell"}:
        reject("setup type must be Buy or Sell")
    elif expected_type and trade_type != expected_type:
        reject("setup type must align with higher timeframe bias")

    session = normalized_text(snapshot.get("session"))
    if session not in ALLOWED_SESSIONS:
        reject("trade is outside London or New York session")

    trades_taken = to_int(first_present(snapshot, "trades_taken_in_session", "session_trade_count"), 0)
    if trades_taken >= 2:
        reject("maximum two trades per session already reached")

    volatility = mapping(snapshot.get("volatility"))
    volatility_state = normalized_text(first_present(volatility, "state", "condition"))
    if bool_value(first_present(snapshot, "low_volatility", "is_low_volatility")):
        reject("low volatility")
    if volatility_state in {"low", "quiet", "dead"}:
        reject("low volatility")
    if bool_value(first_present(snapshot, "choppy", "is_choppy")) or bool_value(volatility.get("choppy")):
        reject("choppy conditions")

    htf_structure = normalized_text(first_present(htf, "structure", "major_structure"))
    if htf_structure not in VALID_STRUCTURE_EVENTS:
        reject("higher timeframe BOS or CHoCH is missing")
    if not has_value(first_present(htf, "liquidity_zones", "key_liquidity_zones")):
        reject("higher timeframe liquidity zones are missing")

    m5 = mapping(first_present(snapshot, "m5", "m5_market_structure", "market_structure"))
    m5_trend = normalized_text(first_present(m5, "trend", "intraday_trend"))
    m5_event = normalized_text(first_present(m5, "structure", "structure_shift", "event"))
    if expected_type and m5_trend != htf_bias:
        reject("M5 trend does not align with higher timeframe bias")
    if m5_event not in VALID_STRUCTURE_EVENTS:
        reject("M5 BOS or CHoCH is missing")
    if not bool_value(first_present(m5, "momentum_shift", "momentum_shift_detected")):
        reject("M5 momentum shift is missing")

    liquidity = mapping(snapshot.get("liquidity"))
    liquidity_sweep = bool_value(first_present(liquidity, "sweep", "liquidity_sweep", "sweep_present"))
    sweep_side = normalized_text(first_present(liquidity, "sweep_side", "swept_side"))
    if not liquidity_sweep:
        reject("liquidity sweep is missing")
    if expected_type == "buy" and sweep_side not in {"sell-side", "sell side", "sellside", "lows"}:
        reject("buy setup requires sell-side liquidity sweep")
    if expected_type == "sell" and sweep_side not in {"buy-side", "buy side", "buyside", "highs"}:
        reject("sell setup requires buy-side liquidity sweep")
    if not has_value(first_present(liquidity, "buy_side", "buy_side_liquidity")):
        reject("buy-side liquidity is not marked")
    if not has_value(first_present(liquidity, "sell_side", "sell_side_liquidity")):
        reject("sell-side liquidity is not marked")

    zones = mapping(snapshot.get("zones"))
    if expected_type == "buy" and not has_value(first_present(zones, "demand", "demand_zone")):
        reject("demand zone is missing")
    if expected_type == "sell" and not has_value(first_present(zones, "supply", "supply_zone")):
        reject("supply zone is missing")
    order_block = mapping(first_present(zones, "order_block", "ob"))
    if not is_valid_zone(order_block):
        reject("valid order block is missing")
    elif expected_type and normalized_text(first_present(order_block, "type", "side")) not in {
        expected_zone_type(expected_type),
        expected_type,
    }:
        reject("order block does not match setup direction")
    fvg = mapping(first_present(zones, "fair_value_gap", "fvg"))
    if not is_valid_zone(fvg):
        reject("valid fair value gap is missing")

    indicators = mapping(snapshot.get("indicators"))
    ema20 = to_float(first_present(indicators, "ema20", "ema_20"))
    ema50 = to_float(first_present(indicators, "ema50", "ema_50"))
    if ema20 is None or ema50 is None:
        reject("EMA 20 and EMA 50 are missing")
    elif expected_type == "buy" and ema20 <= ema50:
        reject("EMA alignment is not bullish")
    elif expected_type == "sell" and ema20 >= ema50:
        reject("EMA alignment is not bearish")

    rsi = to_float(indicators.get("rsi"))
    if rsi is None:
        reject("RSI is missing")
    elif expected_type == "buy" and rsi >= 70:
        reject("buy entry is RSI-overextended")
    elif expected_type == "sell" and rsi <= 30:
        reject("sell entry is RSI-overextended")

    adx = to_float(indicators.get("adx"))
    strong_displacement = bool_value(
        first_present(indicators, "strong_displacement", "displacement_candle")
    ) or bool_value(first_present(snapshot, "strong_displacement", "displacement_candle"))
    if not ((adx is not None and adx > 20) or strong_displacement):
        reject("ADX is not above 20 and no strong displacement candle is present")

    confirmation = mapping(snapshot.get("confirmation"))
    confirmation_sweep = bool_value(
        first_present(confirmation, "liquidity_sweep", "sweep")
    ) or liquidity_sweep
    rejection_or_displacement = bool_value(
        first_present(
            confirmation,
            "rejection_or_displacement",
            "strong_rejection",
            "displacement",
        )
    )
    candle = normalized_text(first_present(confirmation, "candle", "candle_confirmation"))
    reclaim = bool_value(first_present(confirmation, "reclaim_key_level", "key_level_reclaim", "reclaim"))
    if not confirmation_sweep:
        reject("confirmation liquidity sweep is missing")
    if not rejection_or_displacement:
        reject("strong rejection or displacement confirmation is missing")
    if candle not in VALID_CANDLES:
        reject("engulfing or impulse candle confirmation is missing")
    if not reclaim:
        reject("key level reclaim is missing")

    entry = parse_entry(first_present(setup, "entry", "entry_range"))
    stop_loss = to_float(first_present(setup, "stop_loss", "sl"))
    tp1 = to_float(first_present(setup, "take_profit_1", "tp1"))
    tp2 = to_float(first_present(setup, "take_profit_2", "tp2"))
    score = to_float(first_present(setup, "score", "setup_score"))
    stop_basis = normalized_text(first_present(setup, "stop_loss_basis", "stop_loss_source", "sl_basis"))

    if entry is None:
        reject("entry is missing or invalid")
    elif entry.width > 1:
        reject("entry range is wider than 1 USD")
    if stop_loss is None:
        reject("stop loss is missing")
    if tp1 is None or tp2 is None:
        reject("take profits are missing")
    if not any(term in stop_basis for term in STRUCTURE_STOP_TERMS):
        reject("stop loss is not structure-based")
    if score is None:
        reject("setup score is missing")
    elif score < 7:
        reject("setup score is below 7")
    elif score > 10:
        reject("setup score is above 10")

    risk_reward: float | None = None
    if entry is not None and stop_loss is not None and tp1 is not None and tp2 is not None:
        price_reason = validate_price_geometry(expected_type, entry, stop_loss, tp1, tp2)
        if price_reason:
            reject(price_reason)
        else:
            risk_reward = calculate_risk_reward(expected_type, entry, stop_loss, tp2)
            if risk_reward is None or risk_reward < 2:
                reject("risk/reward is below 1:2")

    if reasons:
        return TradeDecision(False, NO_TRADE, tuple(reasons))

    assert entry is not None
    assert stop_loss is not None
    assert tp1 is not None
    assert tp2 is not None
    assert score is not None
    assert risk_reward is not None
    assert expected_type in {"buy", "sell"}

    output = format_trade(
        market_bias=title_bias(htf_bias),
        trade_type=expected_type.title(),
        entry=entry,
        stop_loss=stop_loss,
        tp1=tp1,
        tp2=tp2,
        risk_reward=risk_reward,
        score=score,
        candle=candle,
        reasoning=str(
            first_present(setup, "reasoning")
            or default_reasoning(expected_type, htf_structure, m5_event, sweep_side, indicators)
        ),
    )
    return TradeDecision(True, output)


def format_decision(decision: TradeDecision) -> str:
    """Return the exact text intended for external output."""

    return decision.output


def format_trade(
    *,
    market_bias: str,
    trade_type: str,
    entry: EntryRange,
    stop_loss: float,
    tp1: float,
    tp2: float,
    risk_reward: float,
    score: float,
    candle: str,
    reasoning: str,
) -> str:
    return "\n".join(
        [
            f"Market Bias: {market_bias}",
            f"Setup Type: {trade_type}",
            f"Entry: {entry.display()}",
            f"Stop Loss: {format_price(stop_loss)}",
            f"Take Profits: TP1 {format_price(tp1)}, TP2 {format_price(tp2)}",
            f"Risk/Reward: 1:{risk_reward:.2f}",
            f"Score: {score:g}/10",
            f"Confirmation: Liquidity sweep + {candle} candle + key-level reclaim",
            f"Reasoning: {reasoning}",
        ]
    )


def parse_entry(value: Any) -> EntryRange | None:
    if isinstance(value, Mapping):
        low = to_float(first_present(value, "low", "from", "min"))
        high = to_float(first_present(value, "high", "to", "max"))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) != 2:
            return None
        low = to_float(value[0])
        high = to_float(value[1])
    else:
        low = high = to_float(value)

    if low is None or high is None:
        return None
    if low > high:
        low, high = high, low
    return EntryRange(low=low, high=high)


def validate_price_geometry(
    trade_type: str, entry: EntryRange, stop_loss: float, tp1: float, tp2: float
) -> str | None:
    if trade_type == "buy":
        if not (stop_loss < entry.low <= entry.high < tp1 <= tp2):
            return "buy price geometry is invalid"
    elif trade_type == "sell":
        if not (tp2 <= tp1 < entry.low <= entry.high < stop_loss):
            return "sell price geometry is invalid"
    else:
        return "trade direction is invalid"
    return None


def calculate_risk_reward(
    trade_type: str, entry: EntryRange, stop_loss: float, tp2: float
) -> float | None:
    if trade_type == "buy":
        entry_price = entry.high
        risk = entry_price - stop_loss
        reward = tp2 - entry_price
    elif trade_type == "sell":
        entry_price = entry.low
        risk = stop_loss - entry_price
        reward = entry_price - tp2
    else:
        return None
    if risk <= 0:
        return None
    return reward / risk


def is_valid_zone(zone: Mapping[str, Any]) -> bool:
    if not zone:
        return False
    if "valid" in zone and not bool_value(zone["valid"]):
        return False
    if "low" in zone and "high" in zone:
        return to_float(zone["low"]) is not None and to_float(zone["high"]) is not None
    return has_value(zone)


def expected_zone_type(expected_type: str) -> str:
    return "demand" if expected_type == "buy" else "supply"


def default_reasoning(
    expected_type: str,
    htf_structure: str,
    m5_event: str,
    sweep_side: str,
    indicators: Mapping[str, Any],
) -> str:
    ema_phrase = "EMA20 above EMA50" if expected_type == "buy" else "EMA20 below EMA50"
    adx = to_float(indicators.get("adx"))
    momentum = f"ADX {adx:g}" if adx is not None and adx > 20 else "strong displacement"
    return (
        f"HTF {htf_structure.upper()} and M5 {m5_event.upper()} align after {sweep_side} "
        f"liquidity sweep; valid order block/FVG, {ema_phrase}, and {momentum} confirm momentum."
    )


def first_present(source: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in source and source[key] is not None:
            return source[key]
    return None


def mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def normalized_text(value: Any) -> str:
    return str(value).strip().lower() if value is not None else ""


def title_bias(value: str) -> str:
    return "Bullish" if value == "bullish" else "Bearish"


def bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "y", "1", "present", "valid"}
    return bool(value)


def has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return bool(value)
    if isinstance(value, Mapping):
        return bool(value)
    return True


def to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_int(value: Any, default: int) -> int:
    if value is None or isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def format_price(value: float) -> str:
    return f"{value:.2f}"
