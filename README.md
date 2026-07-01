# Niawj

Dependency-free Python evaluator for strict XAUUSD scalping setups on the
5-minute timeframe.

## Strategy behavior

`evaluate_xauusd_scalp` returns exactly one formatted setup only when all
mandatory rules align:

- London or New York session only, with a maximum of two signals per session.
- M15 and H1 bias agree as Bullish or Bearish.
- M5 EMA 20/50 alignment matches the higher-timeframe bias.
- Liquidity sweep, reclaim, and engulfing or impulse candle confirmation.
- Tradeable volatility via ADX above 20 or a strong displacement candle.
- Valid order block, fair value gap, structure-based stop, and at least 1:2 RR.

If any required condition is missing, the evaluator returns:

```text
No trade – conditions not met
```

## Verification

```bash
python3 -m unittest discover -s tests
```