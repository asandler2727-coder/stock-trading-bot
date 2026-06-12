"""
Data layer for stockslab.

Public API (frozen contract):
    UNIVERSE: dict[str, dict]     symbol -> {"kind": "etf"|"levered"|"stock", "tier": 1|2|3}
    fetch(symbol, interval, start=None, force=False) -> pd.DataFrame
    load_panel(symbols, interval, start=None) -> dict[str, pd.DataFrame]
    splits(interval) -> tuple[slice, slice]
    validate(df)   — raises ValueError on schema violations

Cache layout: CACHE_DIR/{interval}/{symbol}.parquet
  CACHE_DIR defaults to <repo-root>/data but can be monkeypatched in tests.

Data schema (contract):
  - Index: DatetimeIndex named "date"
      - daily  → tz-naive
      - intraday → America/New_York
  - Columns: exactly ["open", "high", "low", "close", "volume"] (float64, lowercase)
  - Strictly increasing index (monotonic, no duplicates)
  - No NaN rows
"""

from __future__ import annotations

import pathlib
import time
import logging
from typing import Optional

import numpy as np

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# Resolve repo root relative to this file's location:
#   src/stockslab/data.py → parent.parent.parent = repo root
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
CACHE_DIR: pathlib.Path = _REPO_ROOT / "data"

# ---------------------------------------------------------------------------
# UNIVERSE
# ---------------------------------------------------------------------------

# Tier mapping (per-side slippage bps):
#   1 = 1 bp  (major ETFs)
#   2 = 3 bps (megacap stocks)
#   3 = 5 bps (other stocks + leveraged ETFs)

_PLAIN_ETFS: list[str] = [
    "SPY", "QQQ", "IWM", "DIA",
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLP",
    "XLU", "XLY", "XLB", "XLRE", "XLC",
    "GLD", "SLV", "TLT", "HYG", "EEM", "EFA",
]

_LEVERED_ETFS: list[str] = ["TQQQ", "SQQQ", "SOXL", "SOXS", "UPRO", "TNA", "UVXY"]

# S&P 100 current constituents (as of June 2026)
_SP100: list[str] = [
    "AAPL", "MSFT", "AMZN", "NVDA", "GOOGL", "GOOG", "META", "TSLA", "BRK.B",
    "JPM", "UNH", "XOM", "JNJ", "V", "PG", "MA", "HD", "CVX", "MRK", "ABBV",
    "AVGO", "PEP", "KO", "COST", "ADBE", "WMT", "MCD", "CSCO", "ABT", "BAC",
    "TMO", "CRM", "ACN", "PFE", "LIN", "DHR", "TXN", "NEE", "NKE", "QCOM",
    "PM", "ORCL", "AMGN", "HON", "IBM", "MDT", "RTX", "LOW", "UPS", "CAT",
    "INTU", "SBUX", "GE", "AMAT", "GILD", "BKNG", "NOW", "AXP", "ELV", "ISRG",
    "MDLZ", "BMY", "VRTX", "ADI", "REGN", "MMC", "PLD", "ZTS", "SYK", "C",
    "DE", "TJX", "MU", "LRCX", "ETN", "BSX", "CI", "SO", "KLAC", "NOC",
    "BLK", "GS", "MS", "SPGI", "CB", "ADP", "DUK", "USB", "ITW", "MMM",
    "AON", "WM", "CME", "D", "TGT", "EMR", "PNC", "FCX", "NSC", "ECL",
    "F", "GM",
]

# ~30 liquid / high-beta names from Task A3 step 2
_HIGH_BETA: list[str] = [
    "AMD", "PLTR", "COIN", "MSTR", "SMCI", "SNOW", "NET", "SHOP",
    "SQ", "ROKU", "DKNG", "RIVN", "SOFI", "HOOD", "MARA", "RIOT",
    "CLF", "AA", "OXY", "DVN", "FCX", "ENPH", "U", "RBLX",
    "ABNB", "DASH", "UBER", "LYFT", "ZM", "CRWD",
]

# Megacap stocks that get tier 2 (3 bps slippage) — large enough to be liquid
_MEGACAP_STOCKS: set[str] = {
    "AAPL", "MSFT", "AMZN", "NVDA", "GOOGL", "GOOG", "META", "TSLA",
    "BRK.B", "JPM", "UNH", "XOM", "JNJ", "V", "PG", "MA", "HD", "CVX",
    "MRK", "ABBV", "AVGO", "PEP", "KO", "COST", "ADBE", "WMT", "MCD",
    "CSCO", "ABT", "BAC",
}


def _build_universe() -> dict[str, dict]:
    u: dict[str, dict] = {}

    for sym in _PLAIN_ETFS:
        u[sym] = {"kind": "etf", "tier": 1}

    for sym in _LEVERED_ETFS:
        u[sym] = {"kind": "levered", "tier": 3}

    seen: set[str] = set()
    for sym in _SP100 + _HIGH_BETA:
        if sym in seen:
            continue
        seen.add(sym)
        tier = 2 if sym in _MEGACAP_STOCKS else 3
        u[sym] = {"kind": "stock", "tier": tier}

    return u


UNIVERSE: dict[str, dict] = _build_universe()

# ---------------------------------------------------------------------------
# Schema constants
# ---------------------------------------------------------------------------

_REQUIRED_COLS: tuple[str, ...] = ("open", "high", "low", "close", "volume")
_INTRADAY_TZ = "America/New_York"

# ---------------------------------------------------------------------------
# validate()
# ---------------------------------------------------------------------------


def validate(df: pd.DataFrame) -> None:
    """Raise ValueError if df does not conform to the contract schema."""
    # Index name
    if df.index.name != "date":
        raise ValueError(
            f"index must be named 'date', got {df.index.name!r}"
        )

    # Columns: exactly the five required ones, lowercase
    if set(df.columns) != set(_REQUIRED_COLS):
        raise ValueError(
            f"DataFrame must have exactly columns {_REQUIRED_COLS}, "
            f"got {sorted(df.columns)}"
        )

    # Monotonically increasing (strict — no duplicates)
    if not df.index.is_monotonic_increasing or df.index.has_duplicates:
        raise ValueError("Index is not strictly monotonically increasing (has duplicates or is unsorted)")

    # No NaN rows
    if df[list(_REQUIRED_COLS)].isnull().any(axis=None):
        raise ValueError("DataFrame contains NaN values in OHLCV columns")

    # Column dtypes: all OHLCV columns must be float64
    for col in _REQUIRED_COLS:
        if df[col].dtype != np.float64:
            raise ValueError(
                f"column '{col}' has dtype {df[col].dtype!r}, expected float64"
            )

    # Timezone: if tz-aware, must be America/New_York (UTC or other tz would
    # break session_vwap, session_exit, and IS/OOS slicing)
    if df.index.tz is not None and str(df.index.tz) != "America/New_York":
        raise ValueError(
            f"tz-aware index must use America/New_York, got {df.index.tz!r}"
        )


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


def _cache_path(symbol: str, interval: str) -> pathlib.Path:
    return CACHE_DIR / interval / f"{symbol}.parquet"


def _write_cache(df: pd.DataFrame, symbol: str, interval: str) -> None:
    path = _cache_path(symbol, interval)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)


def _read_cache(symbol: str, interval: str) -> pd.DataFrame:
    path = _cache_path(symbol, interval)
    if not path.exists():
        raise FileNotFoundError(f"No cached data for {symbol} at {path}")
    df = pd.read_parquet(path)
    return df


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def _normalize(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    """
    Convert yfinance output to the contract schema:
      - Flatten MultiIndex columns if present
      - Keep only open/high/low/close/volume (lowercase)
      - Rename index to 'date'
      - Daily → tz-naive; intraday → America/New_York
    """
    # Flatten MultiIndex (yfinance ≥ 0.2 returns MultiIndex [Price, Ticker])
    if isinstance(df.columns, pd.MultiIndex):
        # Level 0 = price name, level 1 = ticker
        df.columns = [str(col[0]).strip() for col in df.columns]

    # Lowercase all column names
    df.columns = [c.lower().replace(" ", "_") for c in df.columns]

    # Keep only the five required columns
    available = [c for c in _REQUIRED_COLS if c in df.columns]
    df = df[list(available)].copy()

    # Ensure all required columns exist after filtering
    missing = set(_REQUIRED_COLS) - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns after normalization: {missing}")

    # Set index name
    df.index.name = "date"

    # Handle timezone
    if interval == "1d":
        # Make tz-naive
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        # Also normalize any tz-aware to naive
    else:
        # Intraday: ensure America/New_York
        if df.index.tz is None:
            df.index = df.index.tz_localize(_INTRADAY_TZ)
        else:
            df.index = df.index.tz_convert(_INTRADAY_TZ)

    # Drop any rows that are entirely NaN (yfinance sometimes emits these)
    df = df.dropna(how="all")

    # Cast to float64
    df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})

    return df


# ---------------------------------------------------------------------------
# fetch()
# ---------------------------------------------------------------------------


def fetch(
    symbol: str,
    interval: str,
    start: Optional[str] = None,
    force: bool = False,
) -> pd.DataFrame:
    """
    Fetch OHLCV data for *symbol* at *interval* granularity.

    If a valid parquet cache exists and force=False, the cache is returned.
    Otherwise, downloads from yfinance with 3-retry exponential backoff,
    normalizes, validates, and writes to cache.

    Args:
        symbol:   Ticker symbol (e.g. "SPY").
        interval: "1d", "1h", or "5m".
        start:    Start date string "YYYY-MM-DD". Defaults per interval if None.
        force:    If True, re-download even if cache exists.

    Returns:
        pd.DataFrame conforming to the contract schema.
    """
    cache = _cache_path(symbol, interval)

    if not force and cache.exists():
        df = _read_cache(symbol, interval)
        validate(df)
        return df

    # Determine default start
    if start is None:
        if interval == "1d":
            start = "2000-01-01"
        # For intraday, yfinance uses period= parameter instead of start=
        # We'll pass period for 1h/5m and ignore start default

    import yfinance as yf

    # Build kwargs for yfinance download
    dl_kwargs: dict = dict(
        auto_adjust=True,
        progress=False,
    )
    if interval == "1d":
        dl_kwargs["start"] = start
    elif interval == "1h":
        dl_kwargs["period"] = "730d"
    elif interval == "5m":
        dl_kwargs["period"] = "60d"
    else:
        dl_kwargs["start"] = start

    last_exc: Exception = RuntimeError("No attempts made")
    for attempt in range(3):
        try:
            raw = yf.download(symbol, interval=interval, **dl_kwargs)
            if raw is None or raw.empty:
                raise ValueError(f"yfinance returned empty DataFrame for {symbol}")
            df = _normalize(raw, interval)
            validate(df)
            _write_cache(df, symbol, interval)
            return df
        except Exception as exc:
            last_exc = exc
            wait = 2 ** attempt  # 1s, 2s, 4s
            log.warning(
                "fetch(%s, %s) attempt %d/%d failed: %s — retrying in %ds",
                symbol, interval, attempt + 1, 3, exc, wait,
            )
            time.sleep(wait)

    raise RuntimeError(
        f"fetch({symbol}, {interval}) failed after 3 attempts: {last_exc}"
    ) from last_exc


# ---------------------------------------------------------------------------
# load_panel()
# ---------------------------------------------------------------------------


def load_panel(
    symbols: list[str],
    interval: str,
    start: Optional[str] = None,
) -> dict[str, pd.DataFrame]:
    """
    Read cached parquet files for each symbol. Does NOT hit the network.

    Args:
        symbols:  List of ticker symbols.
        interval: "1d", "1h", or "5m".
        start:    Optional date string; rows before this date are dropped.

    Returns:
        dict mapping symbol -> validated DataFrame.

    Raises:
        FileNotFoundError: if a symbol has no cached file.
        ValueError: if a cached file fails validation.
    """
    panel: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        df = _read_cache(sym, interval)
        # Validate before filtering
        validate(df)
        if start is not None:
            df = df.loc[df.index >= pd.Timestamp(start)]
        panel[sym] = df
    return panel


# ---------------------------------------------------------------------------
# splits()
# ---------------------------------------------------------------------------

# 730d ≈ 2 years; 70% IS = first ~511 days, OOS = last ~219 days
# We express intraday splits as date strings rather than fixed row counts
# so downstream code can use .loc[is_slice] on DatetimeIndex frames.
_SPLITS: dict[str, tuple[slice, slice]] = {
    # Daily: intentionally fixed historical window (survivorship-bias known,
    # dates won't change between runs).
    "1d": (
        slice("2010-01-01", "2021-12-31"),
        slice("2022-01-01", "2026-06-01"),
    ),
    # NOTE: intraday dates are anchored to a 2026-06-12 fetch window.
    # If data is re-fetched significantly later these boundaries should be
    # recomputed as (fetch_end - 730d) + 70/30 split.
    "1h": (
        # 730-day window: trailing from 2026-06-12; 70%/30% split
        # IS = 2024-01-05 → 2025-09-02 (~511 days); OOS = 2025-09-03 → 2026-06-12
        slice("2024-01-05", "2025-09-02"),
        slice("2025-09-03", "2026-06-12"),
    ),
    "5m": (
        # 60-day window; too thin to gate — treat entire window as IS, no OOS gate
        slice("2026-04-13", "2026-06-12"),
        slice("2026-04-13", "2026-06-12"),
    ),
}


def splits(interval: str) -> tuple[slice, slice]:
    """
    Return (IS_slice, OOS_slice) for the given interval.

    Raises:
        ValueError: if interval is not recognized.
    """
    if interval not in _SPLITS:
        raise ValueError(
            f"Unknown interval {interval!r}. Valid options: {sorted(_SPLITS)}"
        )
    return _SPLITS[interval]
