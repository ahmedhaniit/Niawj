# Niawj

Strict XAUUSD 5-minute scalping setup evaluator.

The strategy engine accepts a structured market snapshot and returns only:

- one fully validated high-probability setup, or
- `No trade – conditions not met`

It does not fetch market data itself. A scheduler or data adapter should run
every five minutes during London/New York hours, build the snapshot, and pass it
to the evaluator.

## Run

```bash
python -m xauusd_scalper.cli snapshot.json
```

or from stdin:

```bash
cat snapshot.json | python -m xauusd_scalper.cli
```

## Required snapshot fields

The evaluator checks:

- London/New York session only, with fewer than two trades already taken.
- No low-volatility or choppy condition flags.
- M15/H1 bias is `Bullish` or `Bearish`, with BOS/CHoCH and liquidity zones.
- M5 trend aligns with the higher-timeframe bias, with BOS/CHoCH and momentum
  shift.
- Liquidity sweep is present, including sell-side sweep for buys or buy-side
  sweep for sells.
- Directional supply/demand, a valid order block, and a valid FVG.
- EMA20/EMA50 alignment, RSI not overextended, and ADX > 20 or a strong
  displacement candle.
- Entry confirmation: liquidity sweep, strong rejection/displacement,
  engulfing or impulse candle, and key-level reclaim.
- Structure-based stop loss, max $1 entry range, score >= 7, and minimum
  1:2 risk/reward to TP2.

## Example snapshot

```json
{
  "session": "London",
  "trades_taken_in_session": 0,
  "volatility": { "state": "normal", "choppy": false },
  "higher_timeframe": {
    "bias": "Bullish",
    "structure": "BOS",
    "liquidity_zones": ["2630.00 equal lows", "2647.50 prior high"]
  },
  "m5": {
    "trend": "Bullish",
    "structure_shift": "CHoCH",
    "momentum_shift": true
  },
  "liquidity": {
    "sweep": true,
    "sweep_side": "sell-side",
    "buy_side": "2647.50",
    "sell_side": "2630.00"
  },
  "zones": {
    "demand": { "low": 2631.0, "high": 2632.0 },
    "supply": { "low": 2647.0, "high": 2649.0 },
    "order_block": {
      "type": "demand",
      "low": 2631.1,
      "high": 2631.9,
      "valid": true
    },
    "fvg": { "low": 2632.2, "high": 2633.1, "valid": true }
  },
  "indicators": {
    "ema20": 2634.4,
    "ema50": 2633.2,
    "rsi": 61.5,
    "adx": 24.8
  },
  "confirmation": {
    "liquidity_sweep": true,
    "rejection_or_displacement": true,
    "candle": "engulfing",
    "reclaim_key_level": true
  },
  "setup": {
    "type": "Buy",
    "entry": { "low": 2632.2, "high": 2632.9 },
    "stop_loss": 2630.6,
    "take_profit_1": 2637.5,
    "take_profit_2": 2638.6,
    "stop_loss_basis": "structure swing low below swept liquidity",
    "score": 8
  }
}
```