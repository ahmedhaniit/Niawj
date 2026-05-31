"""Rule-based XAUUSD M5 scalping signal engine.

The engine intentionally rejects marginal conditions. It only returns a setup
when higher timeframe bias, M5 structure, liquidity sweep, confirmation candle,
zones, and indicator filters all align.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Literal


NO_TRADE = "No trade – conditions not met"
Direction = Literal["Buy", "Sell"]
Bias = Literal["Bullish", "Bearish"]


@dataclass(frozen=True)
class Candle:
    """OHLCV candle used by the strategy."""

    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass(frozen=True)
class Zone:
    """Price zone such as supply, demand, or FVG."""

    kind: str
    low: float
    high: float


@dataclass(frozen=True)
class Sweep:
    """Detected liquidity sweep and reclaimed reference level."""

    index: int
    level: float
    extreme: float


@dataclass(frozen=True)
class TradeSetup:
    """Validated trade setup ready for formatting."""

    direction: Direction
    bias: Bias
    entry: float
    stop_loss: float
    tp1: float
    tp2: float
    rr: float
    score: int
    confirmation: str
    reasoning: str


def parse_datetime(raw: str) -> datetime:
    """Parse ISO-like timestamps and normalize them to UTC."""

    value = raw.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def read_candles_csv(path: str | Path) -> list[Candle]:
    """Read candles from a CSV with time, open, high, low, close columns."""

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


def active_session(now: datetime) -> str | None:
    """Return the active trading session for the supplied UTC timestamp."""

    utc_now = now.astimezone(timezone.utc)
    minutes = utc_now.hour * 60 + utc_now.minute
    london = 7 * 60 <= minutes < 16 * 60
    new_york = 12 * 60 <= minutes < 21 * 60
    if new_york:
        return "new_york"
    if london:
        return "london"
    return None


def session_key(now: datetime) -> str:
    """Use the UTC date for per-session trade counting."""

    return now.astimezone(timezone.utc).date().isoformat()


def load_trade_state(path: str | Path | None) -> dict[str, dict[str, int]]:
    """Load persisted per-session trade counts."""

    if path is None or not Path(path).exists():
        return {}
    with Path(path).open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("Trade state must be a JSON object")
    return data


def save_trade_state(path: str | Path, state: dict[str, dict[str, int]]) -> None:
    """Persist per-session trade counts."""

    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with state_path.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)
        handle.write("\n")


def can_open_session_trade(
    state: dict[str, dict[str, int]],
    now: datetime,
    max_trades_per_session: int = 2,
) -> bool:
    """Return whether the session is below its maximum signal count."""

    session = active_session(now)
    if session is None:
        return False
    return state.get(session_key(now), {}).get(session, 0) < max_trades_per_session


def record_session_trade(state: dict[str, dict[str, int]], now: datetime) -> dict[str, dict[str, int]]:
    """Increment the active session's trade count."""

    session = active_session(now)
    if session is None:
        return state
    day = session_key(now)
    state.setdefault(day, {})
    state[day][session] = state[day].get(session, 0) + 1
    return state


def ema(values: list[float], period: int) -> list[float]:
    """Compute an exponential moving average series."""

    if not values:
        return []
    multiplier = 2 / (period + 1)
    result = [values[0]]
    for value in values[1:]:
        result.append((value - result[-1]) * multiplier + result[-1])
    return result


def rsi(candles: list[Candle], period: int = 14) -> float:
    """Compute the latest RSI value."""

    if len(candles) <= period:
        return 50.0

    gains = 0.0
    losses = 0.0
    window = candles[-period - 1 :]
    for previous, current in zip(window, window[1:]):
        change = current.close - previous.close
        if change >= 0:
            gains += change
        else:
            losses += abs(change)

    average_gain = gains / period
    average_loss = losses / period
    if average_loss == 0:
        return 100.0
    rs_value = average_gain / average_loss
    return 100 - (100 / (1 + rs_value))


def adx(candles: list[Candle], period: int = 14) -> float:
    """Compute a lightweight latest ADX approximation."""

    if len(candles) <= period:
        return 0.0

    true_ranges: list[float] = []
    plus_dm: list[float] = []
    minus_dm: list[float] = []
    window = candles[-period - 1 :]
    for previous, current in zip(window, window[1:]):
        true_ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
        up_move = current.high - previous.high
        down_move = previous.low - current.low
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0.0)

    atr = sum(true_ranges) / period
    if atr == 0:
        return 0.0
    plus_di = 100 * ((sum(plus_dm) / period) / atr)
    minus_di = 100 * ((sum(minus_dm) / period) / atr)
    if plus_di + minus_di == 0:
        return 0.0
    return 100 * abs(plus_di - minus_di) / (plus_di + minus_di)


def average_range(candles: list[Candle], lookback: int = 20) -> float:
    """Average high-low range over the latest lookback candles."""

    sample = candles[-lookback:]
    if not sample:
        return 0.0
    return sum(candle.high - candle.low for candle in sample) / len(sample)


def average_body(candles: list[Candle], lookback: int = 20) -> float:
    """Average candle body over the latest lookback candles."""

    sample = candles[-lookback:]
    if not sample:
        return 0.0
    return sum(abs(candle.close - candle.open) for candle in sample) / len(sample)


def is_strong_displacement(candles: list[Candle], index: int = -1) -> bool:
    """Return true when the candle body and range show decisive displacement."""

    if len(candles) < 20:
        return False
    candle = candles[index]
    body = abs(candle.close - candle.open)
    range_size = candle.high - candle.low
    prior = candles[:-1] if index == -1 else candles[:index]
    return body >= average_body(prior, 20) * 1.6 and range_size >= average_range(prior, 20) * 1.2


def timeframe_bias(candles: list[Candle]) -> Bias | None:
    """Derive Bullish/Bearish bias from EMA alignment and current price."""

    if len(candles) < 50:
        return None
    closes = [candle.close for candle in candles]
    ema20 = ema(closes, 20)[-1]
    ema50 = ema(closes, 50)[-1]
    close = closes[-1]
    if ema20 > ema50 and close > ema20:
        return "Bullish"
    if ema20 < ema50 and close < ema20:
        return "Bearish"
    return None


def higher_timeframe_bias(m15: list[Candle], h1: list[Candle]) -> Bias | None:
    """Require M15 and H1 to agree before a trade is considered."""

    m15_bias = timeframe_bias(m15)
    h1_bias = timeframe_bias(h1)
    if m15_bias is not None and m15_bias == h1_bias:
        return m15_bias
    return None


def m5_trend(candles: list[Candle]) -> Bias | None:
    """Determine the intraday M5 trend."""

    return timeframe_bias(candles)


def liquidity_tolerance(candles: list[Candle]) -> float:
    """Adaptive tolerance for equal highs/lows and reclaimed levels."""

    return max(0.20, min(1.00, average_range(candles, 20) * 0.35))


def has_equal_liquidity(candles: list[Candle], direction: Direction, lookback: int = 18) -> bool:
    """Check whether recent equal highs or lows are present."""

    if len(candles) < lookback + 2:
        return False
    sample = candles[-lookback - 2 : -2]
    tolerance = liquidity_tolerance(candles)
    prices = [candle.low for candle in sample] if direction == "Buy" else [candle.high for candle in sample]
    for index, price in enumerate(prices):
        for other in prices[index + 1 :]:
            if abs(price - other) <= tolerance:
                return True
    return False


def detect_liquidity_sweep(candles: list[Candle], direction: Direction) -> Sweep | None:
    """Detect a recent sweep of sell-side or buy-side liquidity."""

    if len(candles) < 30:
        return None
    tolerance = liquidity_tolerance(candles)
    start = max(14, len(candles) - 6)
    end = len(candles) - 1
    for index in range(start, end):
        prior = candles[max(0, index - 18) : index]
        if len(prior) < 8:
            continue
        candle = candles[index]
        if direction == "Buy":
            level = min(item.low for item in prior)
            if candle.low < level - tolerance and candle.close > level:
                return Sweep(index=index, level=level, extreme=candle.low)
        else:
            level = max(item.high for item in prior)
            if candle.high > level + tolerance and candle.close < level:
                return Sweep(index=index, level=level, extreme=candle.high)
    return None


def bullish_engulfing(previous: Candle, current: Candle) -> bool:
    """Return true for a bullish engulfing confirmation."""

    return (
        previous.close < previous.open
        and current.close > current.open
        and current.close >= previous.open
        and current.open <= previous.close
    )


def bearish_engulfing(previous: Candle, current: Candle) -> bool:
    """Return true for a bearish engulfing confirmation."""

    return (
        previous.close > previous.open
        and current.close < current.open
        and current.close <= previous.open
        and current.open >= previous.close
    )


def has_candle_confirmation(candles: list[Candle], sweep: Sweep, direction: Direction) -> bool:
    """Require rejection/displacement, candle confirmation, and key-level reclaim."""

    latest = candles[-1]
    previous = candles[-2]
    if sweep.index >= len(candles) - 1:
        return False

    displacement = is_strong_displacement(candles)
    if direction == "Buy":
        reclaimed = latest.close > sweep.level and latest.close > latest.open
        candle_pattern = bullish_engulfing(previous, latest) or displacement
        rejection = candles[sweep.index].close > sweep.level
    else:
        reclaimed = latest.close < sweep.level and latest.close < latest.open
        candle_pattern = bearish_engulfing(previous, latest) or displacement
        rejection = candles[sweep.index].close < sweep.level

    return reclaimed and candle_pattern and rejection


def has_bos_or_choch(candles: list[Candle], direction: Direction) -> bool:
    """Detect a latest-candle break of recent M5 structure."""

    if len(candles) < 15:
        return False
    latest = candles[-1]
    prior = candles[-12:-1]
    if direction == "Buy":
        return latest.close > max(candle.high for candle in prior)
    return latest.close < min(candle.low for candle in prior)


def latest_order_block(candles: list[Candle], direction: Direction) -> Zone | None:
    """Find the last opposite candle before the latest displacement."""

    if len(candles) < 5:
        return None
    for candle in reversed(candles[-12:-1]):
        if direction == "Buy" and candle.close < candle.open:
            return Zone("Demand OB", low=candle.low, high=max(candle.open, candle.close))
        if direction == "Sell" and candle.close > candle.open:
            return Zone("Supply OB", low=min(candle.open, candle.close), high=candle.high)
    return None


def latest_fvg(candles: list[Candle], direction: Direction) -> Zone | None:
    """Identify the most recent three-candle fair value gap."""

    if len(candles) < 3:
        return None
    for index in range(len(candles) - 1, max(1, len(candles) - 12), -1):
        left = candles[index - 2]
        right = candles[index]
        if direction == "Buy" and left.high < right.low:
            return Zone("Bullish FVG", low=left.high, high=right.low)
        if direction == "Sell" and left.low > right.high:
            return Zone("Bearish FVG", low=right.high, high=left.low)
    return None


def indicator_filters(candles: list[Candle], direction: Direction) -> tuple[bool, float, float, bool]:
    """Evaluate EMA alignment, RSI extension, and ADX/displacement filters."""

    closes = [candle.close for candle in candles]
    ema20 = ema(closes, 20)[-1]
    ema50 = ema(closes, 50)[-1]
    latest_rsi = rsi(candles)
    latest_adx = adx(candles)
    displacement = is_strong_displacement(candles)

    if direction == "Buy":
        ema_ok = ema20 > ema50 and closes[-1] > ema20
        rsi_ok = 35 <= latest_rsi <= 76
    else:
        ema_ok = ema20 < ema50 and closes[-1] < ema20
        rsi_ok = 24 <= latest_rsi <= 65

    return ema_ok and rsi_ok and (latest_adx > 20 or displacement), latest_rsi, latest_adx, displacement


def _round_price(value: float) -> float:
    return round(value, 2)


def _rr(entry: float, stop_loss: float, tp2: float, direction: Direction) -> float:
    risk = abs(entry - stop_loss)
    reward = (tp2 - entry) if direction == "Buy" else (entry - tp2)
    if risk <= 0:
        return 0.0
    return reward / risk


def build_setup(candles: list[Candle], bias: Bias, direction: Direction) -> TradeSetup | None:
    """Validate every strategy condition and build a setup if all pass."""

    if bias == "Bullish" and direction != "Buy":
        return None
    if bias == "Bearish" and direction != "Sell":
        return None
    if m5_trend(candles) != bias:
        return None
    if not has_equal_liquidity(candles, direction):
        return None

    sweep = detect_liquidity_sweep(candles, direction)
    if sweep is None:
        return None
    if not has_candle_confirmation(candles, sweep, direction):
        return None
    if not has_bos_or_choch(candles, direction):
        return None

    order_block = latest_order_block(candles, direction)
    fvg = latest_fvg(candles, direction)
    if order_block is None or fvg is None:
        return None

    indicators_ok, latest_rsi, latest_adx, displacement = indicator_filters(candles, direction)
    if not indicators_ok:
        return None

    entry = _round_price(candles[-1].close)
    structure_buffer = max(0.20, average_range(candles, 20) * 0.10)
    if direction == "Buy":
        stop_loss = _round_price(min(sweep.extreme, order_block.low) - structure_buffer)
        risk = entry - stop_loss
        if risk <= 0:
            return None
        tp1 = _round_price(entry + risk)
        tp2 = _round_price(entry + 2 * risk)
    else:
        stop_loss = _round_price(max(sweep.extreme, order_block.high) + structure_buffer)
        risk = stop_loss - entry
        if risk <= 0:
            return None
        tp1 = _round_price(entry - risk)
        tp2 = _round_price(entry - 2 * risk)

    rr_value = _rr(entry, stop_loss, tp2, direction)
    if rr_value < 2:
        return None

    score = 10
    confirmation = (
        f"{direction} liquidity sweep at {sweep.extreme:.2f}, reclaim of {sweep.level:.2f}, "
        f"and {'displacement' if displacement else 'engulfing'} confirmation."
    )
    reasoning = (
        f"M15/H1 {bias.lower()} bias, M5 BOS/CHoCH confirmed after liquidity sweep, "
        f"EMA20/EMA50 aligned, RSI {latest_rsi:.1f}, ADX {latest_adx:.1f}, "
        f"{order_block.kind} {order_block.low:.2f}-{order_block.high:.2f}, "
        f"{fvg.kind} {fvg.low:.2f}-{fvg.high:.2f}. At TP1 close 50% and move SL to breakeven; "
        "let TP2 run only while momentum continues."
    )
    return TradeSetup(
        direction=direction,
        bias=bias,
        entry=entry,
        stop_loss=stop_loss,
        tp1=tp1,
        tp2=tp2,
        rr=rr_value,
        score=score,
        confirmation=confirmation,
        reasoning=reasoning,
    )


def format_setup(setup: TradeSetup) -> str:
    """Format a setup exactly in the requested fields."""

    return "\n".join(
        [
            f"Market Bias: {setup.bias}",
            f"Setup Type: {setup.direction}",
            f"Entry: {setup.entry:.2f}",
            f"Stop Loss: {setup.stop_loss:.2f}",
            f"Take Profits: TP1 {setup.tp1:.2f}, TP2 {setup.tp2:.2f}",
            f"Risk/Reward: 1:{setup.rr:.2f}",
            f"Score: {setup.score}/10",
            f"Confirmation: {setup.confirmation}",
            f"Reasoning: {setup.reasoning}",
        ]
    )


def analyze_market(
    m5: Iterable[Candle],
    m15: Iterable[Candle],
    h1: Iterable[Candle],
    *,
    now: datetime | None = None,
    trade_state: dict[str, dict[str, int]] | None = None,
    max_trades_per_session: int = 2,
) -> str:
    """Analyze the market and return one setup or the strict no-trade message."""

    m5_candles = sorted(list(m5), key=lambda candle: candle.time)
    m15_candles = sorted(list(m15), key=lambda candle: candle.time)
    h1_candles = sorted(list(h1), key=lambda candle: candle.time)
    if len(m5_candles) < 60 or len(m15_candles) < 50 or len(h1_candles) < 50:
        return NO_TRADE

    signal_time = now or m5_candles[-1].time
    if active_session(signal_time) is None:
        return NO_TRADE
    if trade_state is not None and not can_open_session_trade(
        trade_state,
        signal_time,
        max_trades_per_session=max_trades_per_session,
    ):
        return NO_TRADE

    bias = higher_timeframe_bias(m15_candles, h1_candles)
    if bias is None:
        return NO_TRADE

    directions: tuple[Direction, ...] = ("Buy",) if bias == "Bullish" else ("Sell",)
    for direction in directions:
        setup = build_setup(m5_candles, bias, direction)
        if setup is not None and setup.score >= 7:
            return format_setup(setup)

    return NO_TRADE
