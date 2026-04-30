# Niawj

Rule-gated XAUUSD 5-minute scalping setup generation.

The analyzer returns one formatted trade setup only when every institutional
scalping condition is present. If any required condition is missing, the output
is exactly:

```text
No trade – conditions not met
```

## Covered rules

- XAUUSD only, London or New York session only.
- Maximum two valid trades per session via supplied session trade counts.
- M15/H1 bias must be Bullish or Bearish and aligned with M5 trend.
- Higher-timeframe and M5 structure must include BOS or CHoCH.
- Equal highs/lows and a directional liquidity sweep are mandatory.
- Entry must sit inside a relevant supply/demand, order block, or FVG zone.
- EMA 20/50 alignment, non-overextended RSI, and ADX > 20 or displacement are
  required.
- Entry range cannot exceed $1, score must be at least 7, and TP2 must provide
  at least 1:2 risk/reward.
- Confirmation requires liquidity sweep plus rejection/displacement,
  engulfing/impulse candle, and reclaim of a key level.

## Usage

```python
from datetime import time

from niawj.trade_setup import analyze_market, MarketSnapshot

result = analyze_market(
    MarketSnapshot(
        symbol="XAUUSD",
        timestamp_utc=time(8, 15),
        htf=...,
        m5=...,
        liquidity=...,
        key_zones=...,
        indicators=...,
        candidate=...,
        session_trade_counts={"London": 1},
    )
)
```

`analyze_market` returns the required output format:

```text
Market Bias:
Setup Type:
Entry:
Stop Loss:
Take Profits:
Risk/Reward:
Score:
Confirmation:
Reasoning:
```

Use `first_valid_setup` when an execution cycle evaluates several candidates;
it returns only the first valid setup or the no-trade message.