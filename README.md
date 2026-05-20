# Niawj

Strict XAUUSD 5-minute scalping setup evaluator.

The evaluator only emits a setup when every required rule is present in the
provided candle snapshot. If data is missing, the session is inactive, volatility
is weak, liquidity was not swept, confirmation is absent, or risk/reward is below
1:2, it returns exactly:

```text
No trade – conditions not met
```

## Input contract

Provide JSON with `XAUUSD` candles for M5, M15, and H1:

```json
{
  "symbol": "XAUUSD",
  "as_of": "2026-05-20T12:35:00Z",
  "m5": [
    {"timestamp": "2026-05-20T07:40:00Z", "open": 2400.0, "high": 2401.0, "low": 2399.5, "close": 2400.5}
  ],
  "m15": [],
  "h1": []
}
```

Each candle accepts `timestamp` or `time`, plus `open`, `high`, `low`, and
`close`. `volume` is optional.

## Usage

```bash
python -m xauusd_scalper snapshot.json
```

or:

```bash
python -m xauusd_scalper < snapshot.json
```

Track the session trade limit externally and pass the current count:

```bash
python -m xauusd_scalper snapshot.json --session-trades 1
```

## Strategy gates

- London or New York session only.
- Maximum two accepted trades per active session.
- H1 and M15 bias must agree as Bullish or Bearish.
- M5 trend, EMA 20/50 alignment, RSI, ADX/displacement, and volatility must
  support the same direction.
- A buy requires a sell-side liquidity sweep; a sell requires a buy-side sweep.
- Entry confirmation requires rejection or displacement plus reclaim of the
  swept level.
- A recent order block and fair value gap must be present.
- TP1 is set at minimum 1:2 risk/reward; TP2 is set at 1:3.