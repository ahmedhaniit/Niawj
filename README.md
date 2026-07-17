# Niawj

Dependency-free Python evaluator for strict XAUUSD scalping setups on the
5-minute timeframe.

## Strategy behavior

`evaluate_xauusd_scalp` returns exactly one formatted setup only when all
mandatory rules align:

- London or New York session only, with persisted state enforcing a maximum of
  two generated setups per session and blocking duplicate signals for one M5
  candle.
- M15 and H1 bias agree as `Bullish` or `Bearish`, each with a close-confirmed
  BOS/CHoCH and mapped buy-side/sell-side liquidity.
- M5 trend, BOS/CHoCH, and momentum shift align with the higher-timeframe bias.
- Equal highs/lows, a liquidity sweep, rejection, candle confirmation, and
  reclaim of the swept level are present. Rejection requires a meaningful wick,
  not merely a close back through the level.
- A valid demand/supply order block touched by the sweep and a post-sweep fair
  value gap are detected.
- EMA 20/50 alignment, RSI not overextended, and ADX > 20 or a strong
  displacement candle confirm the setup.
- The latest M5 candle is fresh, the stop is structure-based, and TP2 provides
  at least 1:2 risk/reward.

If any required condition is missing, the evaluator returns exactly:

```text
No trade – conditions not met
```

## CSV format

The CLI accepts M5, M15, and H1 CSV files with these columns:

```csv
time,open,high,low,close,volume
2026-07-03T12:00:00Z,2330.10,2332.20,2329.60,2331.70,100
```

`volume` is optional. Timestamps are normalized to UTC.

## Scheduled usage

Run the command after each fresh 5-minute candle is written:

```bash
python3 -m xauusd_scalper.cli \
  --m5 data/xauusd_m5.csv \
  --m15 data/xauusd_m15.csv \
  --h1 data/xauusd_h1.csv \
  --state .runtime/xauusd-session-state.json
```

The state path is mandatory. A successful setup is recorded automatically and
written atomically so later executions can enforce the London/New York cap.
Direct Python callers must likewise pass a loaded `TradeState` and record an
emitted setup. The evaluator does not fetch market data or place trades; it only
evaluates supplied OHLC candles and returns a setup or the no-trade line.

## Verification

```bash
python3 -m unittest discover -s tests
```