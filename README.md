# Niawj

Strict XAUUSD scalping analyzer for the 5-minute timeframe.

The analyzer consumes fresh M5, M15 and H1 OHLC candles and prints exactly one
high-probability setup only when every rule is satisfied. If any gate is
missing, the output is:

```text
No trade – conditions not met
```

## What it checks

- London / New York session filter.
- Maximum two emitted trades per session when a state file is supplied.
- Higher-timeframe M15 / H1 bullish or bearish bias.
- M5 structure shift after a mandatory liquidity sweep.
- Buy-side / sell-side liquidity, order block and recent fair value gap.
- EMA 20 / EMA 50 alignment, RSI not overextended, and ADX > 20 or a strong
  displacement candle.
- Minimum 1:2 risk/reward, with TP1 at 2R and TP2 at 3R.

## Input format

Provide JSON with `m5`, `m15` and `h1` arrays. Each candle needs `time` (or
`timestamp`), `open`, `high`, `low` and `close`; `volume` is optional.

```json
{
  "m5": [
    {
      "time": "2026-06-13T12:00:00Z",
      "open": 3420.10,
      "high": 3422.40,
      "low": 3418.70,
      "close": 3421.80
    }
  ],
  "m15": [],
  "h1": []
}
```

The engine requires at least 60 M5 candles, 35 M15 candles and 20 H1 candles.

## Usage

Run once:

```bash
python -m xauusd_scalper.cli --input snapshot.json --now 2026-06-13T12:05:00Z
```

For a 5-minute scheduler, pass a state file so the analyzer tracks session
trade counts:

```bash
python -m xauusd_scalper.cli \
  --input snapshot.json \
  --now 2026-06-13T12:05:00Z \
  --state-file .state/xauusd-scalper.json
```

When a setup is emitted, manage it as follows: close 50% at TP1, move stop loss
to breakeven, and allow TP2 to run only while momentum continues.