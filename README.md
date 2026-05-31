# Niawj

## XAUUSD M5 scalping analyzer

This repository contains a strict, rule-based XAUUSD scalping analyzer for the
5-minute timeframe. It accepts M5, M15, and H1 OHLC CSV data and returns either
one high-probability setup or exactly:

```text
No trade – conditions not met
```

The engine requires all of the following before it emits a setup:

- London or New York session filter
- M15 and H1 bias alignment
- M5 trend alignment with BOS/CHoCH
- Recent liquidity sweep plus rejection/displacement confirmation
- Equal highs/lows liquidity context
- Valid order block and fair value gap
- EMA 20/50 alignment
- RSI not overextended
- ADX above 20 or a strong displacement candle
- Minimum 1:2 risk/reward
- Maximum two valid setups per session when a state file is supplied

### CSV format

Each CSV must include:

```csv
time,open,high,low,close,volume
2026-05-31T12:00:00Z,2330.1,2332.2,2329.6,2331.7,100
```

`volume` is optional. Timestamps are normalized to UTC.

### Usage

```bash
python -m xauusd_scalper.cli \
  --m5 data/xauusd_m5.csv \
  --m15 data/xauusd_m15.csv \
  --h1 data/xauusd_h1.csv \
  --state .runtime/xauusd-session-state.json \
  --record
```

Run the command from a 5-minute scheduler after fresh candles are written. Use
`--record` with `--state` to count generated setups against the London/New York
session limit.

### Testing

```bash
python -m unittest discover -s tests
```