"""
历史行情特征计算
Market feature engineering helpers
"""

from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd


def _numeric_series(df: pd.DataFrame, column: str, fallback: pd.Series) -> pd.Series:
    """Return a numeric column aligned to fallback, or fallback when missing."""
    if column not in df.columns:
        return fallback.copy()
    values = pd.to_numeric(df[column], errors="coerce")
    return values.ffill().bfill().fillna(fallback)


def _last_return(close: pd.Series, periods: int) -> float:
    if len(close) <= periods:
        return np.nan
    base = close.iloc[-periods - 1]
    if base == 0 or pd.isna(base):
        return np.nan
    return (close.iloc[-1] / base - 1) * 100


def _max_drawdown(close: pd.Series) -> float:
    if close.empty:
        return np.nan
    running_max = close.cummax()
    drawdown = close / running_max - 1
    return abs(drawdown.min()) * 100


def _rsi(close: pd.Series, period: int = 14) -> float:
    delta = close.diff().dropna()
    if len(delta) == 0:
        return 50.0
    gain = delta.clip(lower=0).tail(period).mean()
    loss = (-delta.clip(upper=0)).tail(period).mean()
    if pd.isna(gain) or pd.isna(loss) or gain + loss == 0:
        return 50.0
    return float(100 * gain / (gain + loss))


def _macd(close: pd.Series) -> tuple[float, float, float]:
    if close.empty:
        return 0.0, 0.0, 0.0
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal_line
    return (
        float(macd_line.iloc[-1]),
        float(signal_line.iloc[-1]),
        float(histogram.iloc[-1]),
    )


def _stochastic(close: pd.Series, high: pd.Series, low: pd.Series, period: int = 14) -> tuple[float, float]:
    if len(close) < period:
        return 50.0, 50.0

    k_values = []
    for i in range(period - 1, len(close)):
        window_high = high.iloc[i - period + 1 : i + 1].max()
        window_low = low.iloc[i - period + 1 : i + 1].min()
        if window_high == window_low:
            k_values.append(50.0)
        else:
            k_values.append(float((close.iloc[i] - window_low) / (window_high - window_low) * 100))

    stoch_k = k_values[-1]
    stoch_d = float(np.mean(k_values[-3:])) if len(k_values) >= 3 else stoch_k
    return stoch_k, stoch_d


def _atr(close: pd.Series, high: pd.Series, low: pd.Series, period: int = 14) -> tuple[float, float]:
    if len(close) < 2:
        return np.nan, np.nan
    prev_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1).dropna()
    if true_range.empty:
        return np.nan, np.nan
    atr = true_range.tail(period).mean()
    atr_percent = atr / close.iloc[-1] * 100 if close.iloc[-1] else np.nan
    return float(atr), float(atr_percent)


def _williams_r(close: pd.Series, high: pd.Series, low: pd.Series, period: int = 14) -> float:
    if len(close) < period:
        return -50.0
    highest_high = high.tail(period).max()
    lowest_low = low.tail(period).min()
    if highest_high == lowest_low:
        return -50.0
    return float(-100 * (highest_high - close.iloc[-1]) / (highest_high - lowest_low))


def _cci(close: pd.Series, high: pd.Series, low: pd.Series, period: int = 20) -> float:
    if len(close) < period:
        return 0.0
    typical_price = (high.tail(period) + low.tail(period) + close.tail(period)) / 3
    sma = typical_price.mean()
    mean_deviation = (typical_price - sma).abs().mean()
    if mean_deviation == 0 or pd.isna(mean_deviation):
        return 0.0
    return float((typical_price.iloc[-1] - sma) / (0.015 * mean_deviation))


def _obv(close: pd.Series, volume: pd.Series) -> tuple[float, float]:
    if len(close) < 2:
        return 0.0, 0.0
    direction = np.sign(close.diff().fillna(0))
    obv_series = (direction * volume).cumsum()
    obv = float(obv_series.iloc[-1])
    obv_change = float(obv_series.diff(20).iloc[-1]) if len(obv_series) > 20 else float(obv_series.iloc[-1])
    return obv, obv_change


def calculate_price_features(df: pd.DataFrame) -> Dict[str, float]:
    """
    将统一日线数据转换为选股/回测共用的点时特征。

    The function only uses rows already present in ``df`` so it is safe for
    point-in-time backtests when callers slice history up to the signal date.
    """
    if df is None or df.empty:
        raise ValueError("empty price history")

    history = df.copy()
    if "日期" in history.columns:
        history = history.sort_values("日期")

    close = pd.to_numeric(history["收盘"], errors="coerce").ffill().bfill()
    high = _numeric_series(history, "最高", close)
    low = _numeric_series(history, "最低", close)
    volume = _numeric_series(history, "成交量", pd.Series(1.0, index=history.index)).fillna(1.0)
    turnover = _numeric_series(history, "换手率", pd.Series(np.nan, index=history.index))
    amount = _numeric_series(history, "成交额", pd.Series(np.nan, index=history.index))

    if close.empty or pd.isna(close.iloc[-1]):
        raise ValueError("invalid close prices")

    returns = close.pct_change().dropna()
    downside_returns = returns[returns < 0]

    ma5 = close.tail(5).mean()
    ma20 = close.tail(20).mean()
    ma60 = close.tail(60).mean() if len(close) >= 60 else ma20
    ma120 = close.tail(120).mean() if len(close) >= 120 else ma60

    macd_line, signal_line, macd_histogram = _macd(close)
    stoch_k, stoch_d = _stochastic(close, high, low)
    atr, atr_percent = _atr(close, high, low)
    obv, obv_change = _obv(close, volume)

    if len(close) >= 20:
        recent_high = high.tail(20).max()
        recent_low = low.tail(20).min()
        price_position = (
            (close.iloc[-1] - recent_low) / (recent_high - recent_low) * 100
            if recent_high > recent_low
            else 50.0
        )
        path = close.tail(21).pct_change().abs().sum()
        direction = abs(close.iloc[-1] / close.iloc[-21] - 1) if len(close) >= 21 and close.iloc[-21] else 0
        trend_strength = min(direction / path * 100, 100) if path > 0 else 0.0
    else:
        price_position = 50.0
        trend_strength = 0.0

    if len(close) >= 20:
        bb_ma = close.tail(20).mean()
        bb_std = close.tail(20).std(ddof=0)
        bb_upper = bb_ma + 2 * bb_std
        bb_lower = bb_ma - 2 * bb_std
        bb_width = (bb_upper - bb_lower) / bb_ma * 100 if bb_ma > 0 else np.nan
        bb_percent = (close.iloc[-1] - bb_lower) / (bb_upper - bb_lower) * 100 if bb_upper > bb_lower else 50.0
    else:
        bb_upper = close.iloc[-1]
        bb_lower = close.iloc[-1]
        bb_width = np.nan
        bb_percent = 50.0

    volatility = returns.tail(90).std(ddof=1) * np.sqrt(252) * 100 if len(returns) >= 2 else np.nan
    downside_volatility = (
        downside_returns.tail(90).std(ddof=1) * np.sqrt(252) * 100
        if len(downside_returns) >= 2
        else np.nan
    )

    volume_ma5 = volume.tail(5).mean() if len(volume) >= 5 else volume.mean()
    volume_ma20 = volume.tail(20).mean() if len(volume) >= 20 else volume.mean()
    volume_ratio = volume.iloc[-1] / volume_ma20 if volume_ma20 > 0 else 1.0
    volume_momentum = volume_ma5 / volume_ma20 if volume_ma20 > 0 else 1.0

    returns_20d = _last_return(close, 20)
    returns_60d = _last_return(close, 60)

    return {
        "current_price": float(close.iloc[-1]),
        "prices_90d": close.tail(120).to_numpy(),
        "ma5": float(ma5),
        "ma20": float(ma20),
        "ma60": float(ma60),
        "ma120": float(ma120),
        "ma20_distance": float((close.iloc[-1] / ma20 - 1) * 100) if ma20 else np.nan,
        "ma60_distance": float((close.iloc[-1] / ma60 - 1) * 100) if ma60 else np.nan,
        "rsi": float(np.clip(_rsi(close), 0, 100)),
        "macd": macd_line,
        "macd_signal": signal_line,
        "macd_histogram": macd_histogram,
        "stoch_k": float(np.clip(stoch_k, 0, 100)),
        "stoch_d": float(np.clip(stoch_d, 0, 100)),
        "williams_r": _williams_r(close, high, low),
        "cci": _cci(close, high, low),
        "volatility": float(volatility) if pd.notna(volatility) else np.nan,
        "downside_volatility": float(downside_volatility) if pd.notna(downside_volatility) else np.nan,
        "atr": atr,
        "atr_percent": atr_percent,
        "max_drawdown": _max_drawdown(close),
        "bb_upper": float(bb_upper),
        "bb_lower": float(bb_lower),
        "bb_percent": float(bb_percent),
        "bb_width": float(bb_width) if pd.notna(bb_width) else np.nan,
        "volume_ma20": float(volume_ma20),
        "volume_ratio": float(volume_ratio),
        "volume_momentum": float(volume_momentum),
        "obv": obv,
        "obv_change": obv_change,
        "price_position": float(np.clip(price_position, 0, 100)),
        "trend_strength": float(np.clip(trend_strength, 0, 100)),
        "returns_5d": _last_return(close, 5),
        "returns_20d": returns_20d,
        "returns_60d": returns_60d,
        "returns_120d": _last_return(close, 120),
        "return_acceleration": returns_20d - returns_60d / 3 if pd.notna(returns_20d) and pd.notna(returns_60d) else np.nan,
        "turnover_rate": float(turnover.tail(20).mean()) if turnover.notna().any() else np.nan,
        "amount": float(amount.tail(20).mean()) if amount.notna().any() else np.nan,
    }
