from __future__ import annotations

from collections.abc import Sequence

from .models import Candle


def ema(values: Sequence[float], period: int) -> list[float]:
    if period <= 0:
        raise ValueError("period must be positive")
    if not values:
        return []

    multiplier = 2 / (period + 1)
    result = [float(values[0])]
    for value in values[1:]:
        result.append((float(value) - result[-1]) * multiplier + result[-1])
    return result


def rsi(values: Sequence[float], period: int = 14) -> list[float | None]:
    if period <= 0:
        raise ValueError("period must be positive")
    if len(values) < period + 1:
        return [None] * len(values)

    result: list[float | None] = [None] * len(values)
    gains: list[float] = []
    losses: list[float] = []
    for index in range(1, period + 1):
        change = values[index] - values[index - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    average_gain = sum(gains) / period
    average_loss = sum(losses) / period
    result[period] = _rsi_from_averages(average_gain, average_loss)

    for index in range(period + 1, len(values)):
        change = values[index] - values[index - 1]
        gain = max(change, 0)
        loss = max(-change, 0)
        average_gain = ((average_gain * (period - 1)) + gain) / period
        average_loss = ((average_loss * (period - 1)) + loss) / period
        result[index] = _rsi_from_averages(average_gain, average_loss)

    return result


def _rsi_from_averages(average_gain: float, average_loss: float) -> float:
    if average_loss == 0:
        return 100.0
    relative_strength = average_gain / average_loss
    return 100 - (100 / (1 + relative_strength))


def atr(candles: Sequence[Candle], period: int = 14) -> list[float | None]:
    if period <= 0:
        raise ValueError("period must be positive")
    if not candles:
        return []

    true_ranges = [_true_range(candles, index) for index in range(len(candles))]
    result: list[float | None] = [None] * len(candles)
    if len(candles) < period:
        return result

    average = sum(true_ranges[:period]) / period
    result[period - 1] = average
    for index in range(period, len(candles)):
        average = ((average * (period - 1)) + true_ranges[index]) / period
        result[index] = average
    return result


def adx(candles: Sequence[Candle], period: int = 14) -> list[float | None]:
    if period <= 0:
        raise ValueError("period must be positive")
    if len(candles) < period * 2:
        return [None] * len(candles)

    plus_dm = [0.0]
    minus_dm = [0.0]
    true_ranges = [_true_range(candles, 0)]

    for index in range(1, len(candles)):
        current = candles[index]
        previous = candles[index - 1]
        up_move = current.high - previous.high
        down_move = previous.low - current.low
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0.0)
        true_ranges.append(_true_range(candles, index))

    smoothed_tr = sum(true_ranges[1 : period + 1])
    smoothed_plus = sum(plus_dm[1 : period + 1])
    smoothed_minus = sum(minus_dm[1 : period + 1])

    dx_values: list[float | None] = [None] * len(candles)
    for index in range(period, len(candles)):
        if index > period:
            smoothed_tr = smoothed_tr - (smoothed_tr / period) + true_ranges[index]
            smoothed_plus = smoothed_plus - (smoothed_plus / period) + plus_dm[index]
            smoothed_minus = smoothed_minus - (smoothed_minus / period) + minus_dm[index]

        if smoothed_tr == 0:
            dx_values[index] = 0.0
            continue

        plus_di = 100 * (smoothed_plus / smoothed_tr)
        minus_di = 100 * (smoothed_minus / smoothed_tr)
        denominator = plus_di + minus_di
        dx_values[index] = 0.0 if denominator == 0 else 100 * abs(plus_di - minus_di) / denominator

    result: list[float | None] = [None] * len(candles)
    first_adx_index = period * 2 - 1
    initial_dx = [value for value in dx_values[period:first_adx_index + 1] if value is not None]
    if len(initial_dx) < period:
        return result

    average_adx = sum(initial_dx) / period
    result[first_adx_index] = average_adx
    for index in range(first_adx_index + 1, len(candles)):
        dx = dx_values[index]
        if dx is None:
            continue
        average_adx = ((average_adx * (period - 1)) + dx) / period
        result[index] = average_adx
    return result


def _true_range(candles: Sequence[Candle], index: int) -> float:
    current = candles[index]
    if index == 0:
        return current.range
    previous_close = candles[index - 1].close
    return max(
        current.high - current.low,
        abs(current.high - previous_close),
        abs(current.low - previous_close),
    )
