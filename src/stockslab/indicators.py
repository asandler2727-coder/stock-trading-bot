"""Technical indicators for the stockslab backtest lab.

All functions:
  - Return pd.Series aligned to the input index
  - Produce NaN during the warm-up period
  - Are strictly causal (no future leakage): the value at bar t uses only data
    available through bar t

Wilder smoothing: seeded with the simple mean of the first n values, then
the exponential update  new = (prev * (n-1) + value) / n  (alpha = 1/n).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Simple Moving Average
# ---------------------------------------------------------------------------

def sma(series: pd.Series, n: int) -> pd.Series:
    """Simple moving average of length n.

    Parameters
    ----------
    series : pd.Series
        Input price (or any) series.
    n : int
        Look-back window.

    Returns
    -------
    pd.Series
        Aligned to ``series``; first ``n-1`` values are NaN.
    """
    return series.rolling(window=n, min_periods=n).mean()


# ---------------------------------------------------------------------------
# Exponential Moving Average
# ---------------------------------------------------------------------------

def ema(series: pd.Series, n: int) -> pd.Series:
    """Exponential moving average with span=n (alpha = 2/(n+1)).

    Seeded by the simple mean of the first n values; first n-1 values
    are NaN (warm-up).

    Parameters
    ----------
    series : pd.Series
        Input series.
    n : int
        EMA span.

    Returns
    -------
    pd.Series
        Aligned to ``series``; first ``n-1`` values are NaN.
    """
    alpha = 2.0 / (n + 1)
    result = np.full(len(series), np.nan)
    values = series.values.astype(float)

    # Find the seed point: first complete window
    # Seed = simple mean of first n values
    seed_idx = n - 1
    if seed_idx >= len(values):
        return pd.Series(result, index=series.index)

    result[seed_idx] = np.mean(values[:n])

    # Tick forward from the seed
    for i in range(seed_idx + 1, len(values)):
        result[i] = alpha * values[i] + (1 - alpha) * result[i - 1]

    return pd.Series(result, index=series.index)


# ---------------------------------------------------------------------------
# RSI (Wilder smoothing)
# ---------------------------------------------------------------------------

def rsi(series: pd.Series, n: int = 14) -> pd.Series:
    """Relative Strength Index using Wilder's smoothing method.

    Warm-up: the first RSI value appears at bar ``n`` (index n).
    First ``n`` values are NaN.

    Seed: avg_gain and avg_loss are the simple means of the first n
    price changes (bars 0→1 through bars n-1→n).

    Parameters
    ----------
    series : pd.Series
        Close price series.
    n : int
        Look-back period (default 14).

    Returns
    -------
    pd.Series
        Aligned to ``series``; first ``n`` values are NaN.
    """
    values = series.values.astype(float)
    m = len(values)
    result = np.full(m, np.nan)

    if m <= n:
        return pd.Series(result, index=series.index)

    # Compute changes
    changes = np.diff(values)  # length m-1

    # Seed using simple average of first n changes
    first_changes = changes[:n]
    gains = np.where(first_changes > 0, first_changes, 0.0)
    losses = np.where(first_changes < 0, -first_changes, 0.0)

    avg_gain = gains.mean()
    avg_loss = losses.mean()

    # First RSI value at index n
    if avg_loss == 0.0:
        result[n] = 100.0
    elif avg_gain == 0.0:
        result[n] = 0.0
    else:
        rs = avg_gain / avg_loss
        result[n] = 100.0 - 100.0 / (1.0 + rs)

    # Wilder smoothing for subsequent bars
    for i in range(n + 1, m):
        change = changes[i - 1]  # change between bar i-1 and bar i
        gain = change if change > 0 else 0.0
        loss = -change if change < 0 else 0.0

        avg_gain = (avg_gain * (n - 1) + gain) / n
        avg_loss = (avg_loss * (n - 1) + loss) / n

        if avg_loss == 0.0:
            result[i] = 100.0
        elif avg_gain == 0.0:
            result[i] = 0.0
        else:
            rs = avg_gain / avg_loss
            result[i] = 100.0 - 100.0 / (1.0 + rs)

    return pd.Series(result, index=series.index)


# ---------------------------------------------------------------------------
# ATR (Wilder's Average True Range)
# ---------------------------------------------------------------------------

def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Average True Range using Wilder's smoothing.

    True Range = max(high-low, |high-prev_close|, |low-prev_close|).
    The first bar has no previous close; its TR = high - low.

    Seed: simple mean of first n TRs (bars 0 through n-1).
    First ATR value appears at index ``n-1``; first ``n-1`` values are NaN.

    Parameters
    ----------
    df : pd.DataFrame
        Must have columns: high, low, close.
    n : int
        ATR period (default 14).

    Returns
    -------
    pd.Series
        Aligned to ``df.index``; first ``n-1`` values are NaN.
    """
    high = df["high"].values.astype(float)
    low = df["low"].values.astype(float)
    close = df["close"].values.astype(float)
    m = len(close)
    tr = np.empty(m)

    # Bar 0: no previous close
    tr[0] = high[0] - low[0]
    for i in range(1, m):
        hl = high[i] - low[i]
        hpc = abs(high[i] - close[i - 1])
        lpc = abs(low[i] - close[i - 1])
        tr[i] = max(hl, hpc, lpc)

    result = np.full(m, np.nan)
    if m < n:
        return pd.Series(result, index=df.index)

    # Seed: simple mean of first n TRs
    result[n - 1] = tr[:n].mean()

    # Wilder smoothing
    for i in range(n, m):
        result[i] = (result[i - 1] * (n - 1) + tr[i]) / n

    return pd.Series(result, index=df.index)


# ---------------------------------------------------------------------------
# Donchian Channel
# ---------------------------------------------------------------------------

def donchian_high(df: pd.DataFrame, n: int) -> pd.Series:
    """Donchian channel upper band: rolling max of ``high`` over n bars.

    Includes the current bar (window is [t-n+1, t]).
    First ``n-1`` values are NaN.

    Parameters
    ----------
    df : pd.DataFrame
        Must have column ``high``.
    n : int
        Look-back window.

    Returns
    -------
    pd.Series
        Aligned to ``df.index``.
    """
    return df["high"].rolling(window=n, min_periods=n).max()


def donchian_low(df: pd.DataFrame, n: int) -> pd.Series:
    """Donchian channel lower band: rolling min of ``low`` over n bars.

    Includes the current bar (window is [t-n+1, t]).
    First ``n-1`` values are NaN.

    Parameters
    ----------
    df : pd.DataFrame
        Must have column ``low``.
    n : int
        Look-back window.

    Returns
    -------
    pd.Series
        Aligned to ``df.index``.
    """
    return df["low"].rolling(window=n, min_periods=n).min()


# ---------------------------------------------------------------------------
# Bollinger Bands
# ---------------------------------------------------------------------------

def bb(
    series: pd.Series, n: int, k: float
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """Bollinger Bands.

    mid   = SMA(n)
    upper = mid + k * rolling_std(n)
    lower = mid - k * rolling_std(n)
    width = (upper - lower) / mid

    Uses sample std (ddof=1), same as the standard definition.

    Parameters
    ----------
    series : pd.Series
        Close price series.
    n : int
        Look-back window.
    k : float
        Number of standard deviations for the bands.

    Returns
    -------
    tuple[pd.Series, pd.Series, pd.Series, pd.Series]
        (mid, upper, lower, width), each aligned to ``series``.
        First ``n-1`` values are NaN in all four.
    """
    mid = series.rolling(window=n, min_periods=n).mean()
    std = series.rolling(window=n, min_periods=n).std(ddof=1)
    upper = mid + k * std
    lower = mid - k * std
    # width: NaN when mid is NaN or mid == 0
    with np.errstate(divide="ignore", invalid="ignore"):
        width = np.where(
            mid.notna() & (mid != 0.0),
            (upper - lower) / mid,
            np.nan,
        )
    width = pd.Series(width, index=series.index)
    return mid, upper, lower, width


# ---------------------------------------------------------------------------
# Rolling Z-score
# ---------------------------------------------------------------------------

def rolling_zscore(series: pd.Series, n: int) -> pd.Series:
    """Rolling z-score: (value - rolling_mean) / rolling_std.

    Uses sample std (ddof=1).
    First ``n-1`` values are NaN.
    Returns NaN for bars where std == 0 (constant window).

    Parameters
    ----------
    series : pd.Series
        Input series.
    n : int
        Look-back window.

    Returns
    -------
    pd.Series
        Aligned to ``series``.
    """
    roll_mean = series.rolling(window=n, min_periods=n).mean()
    roll_std = series.rolling(window=n, min_periods=n).std(ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        z = np.where(
            roll_std.notna() & (roll_std != 0.0),
            (series - roll_mean) / roll_std,
            np.where(roll_mean.notna(), 0.0, np.nan),
        )
    return pd.Series(z, index=series.index)


# ---------------------------------------------------------------------------
# Session VWAP
# ---------------------------------------------------------------------------

def session_vwap(df: pd.DataFrame) -> pd.Series:
    """Session VWAP that resets each trading day.

    typical_price = (high + low + close) / 3
    VWAP[t] = cumsum(typical_price * volume)[t] / cumsum(volume)[t]

    The cumsum resets at the start of each calendar day (date component of
    the index).

    Parameters
    ----------
    df : pd.DataFrame
        Intraday OHLCV DataFrame. Index must be a DatetimeIndex
        (tz-aware or tz-naive). Must have columns: high, low, close, volume.

    Returns
    -------
    pd.Series
        Aligned to ``df.index``; no NaN values (VWAP is defined from bar 0
        of each session).
    """
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    tpv = tp * df["volume"]

    # Group by date (normalize to midnight)
    date_key = df.index.normalize()

    # Use groupby + cumsum for vectorized computation
    tpv_cumsum = tpv.groupby(date_key).cumsum()
    vol_cumsum = df["volume"].groupby(date_key).cumsum()

    vwap = tpv_cumsum / vol_cumsum
    vwap.name = "vwap"
    return vwap
