from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class Candle:
    """OHLC candle normalized from market-data JSON."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "Candle":
        try:
            timestamp_value = value.get("timestamp") or value.get("time")
            if timestamp_value is None:
                raise ValueError("missing timestamp")

            if isinstance(timestamp_value, (int, float)):
                timestamp = datetime.fromtimestamp(float(timestamp_value), tz=timezone.utc)
            else:
                timestamp = datetime.fromisoformat(str(timestamp_value).replace("Z", "+00:00"))
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)

            return cls(
                timestamp=timestamp.astimezone(timezone.utc),
                open=float(value["open"]),
                high=float(value["high"]),
                low=float(value["low"]),
                close=float(value["close"]),
                volume=float(value["volume"]) if value.get("volume") is not None else None,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid candle: {value!r}") from exc

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def direction(self) -> str:
        if self.close > self.open:
            return "bullish"
        if self.close < self.open:
            return "bearish"
        return "neutral"

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    as_of: datetime
    m5: tuple[Candle, ...]
    m15: tuple[Candle, ...]
    h1: tuple[Candle, ...]

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "MarketSnapshot":
        symbol = str(value.get("symbol", "XAUUSD")).upper()
        as_of_value = value.get("as_of")
        if as_of_value is None:
            m5_raw = value.get("m5") or []
            if not m5_raw:
                raise ValueError("missing as_of and m5 candles")
            as_of = Candle.from_mapping(m5_raw[-1]).timestamp
        else:
            as_of = datetime.fromisoformat(str(as_of_value).replace("Z", "+00:00"))
            if as_of.tzinfo is None:
                as_of = as_of.replace(tzinfo=timezone.utc)

        return cls(
            symbol=symbol,
            as_of=as_of.astimezone(timezone.utc),
            m5=tuple(Candle.from_mapping(candle) for candle in value.get("m5", ())),
            m15=tuple(Candle.from_mapping(candle) for candle in value.get("m15", ())),
            h1=tuple(Candle.from_mapping(candle) for candle in value.get("h1", ())),
        )


@dataclass(frozen=True)
class Zone:
    kind: str
    low: float
    high: float
    source_time: datetime

    @property
    def midpoint(self) -> float:
        return (self.low + self.high) / 2


@dataclass(frozen=True)
class TradeSetup:
    trade_type: str
    entry: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    risk_reward: float
    score: int
    confirmation: str
    reasoning: str
    market_bias: str
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
