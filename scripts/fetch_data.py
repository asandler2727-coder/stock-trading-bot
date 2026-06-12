#!/usr/bin/env python
"""
scripts/fetch_data.py — Download and cache OHLCV data for the universe.

Usage:
    python scripts/fetch_data.py --interval 1d
    python scripts/fetch_data.py --interval 1h
    python scripts/fetch_data.py --interval 5m
    python scripts/fetch_data.py --interval 1d --symbols SPY QQQ AAPL

This script is run MANUALLY after the venv is set up. It hits the network.
Do NOT import this file from tests — tests monkeypatch the cache dir.

Retry logic: 3 attempts with exponential backoff (1s, 2s, 4s) — handled by
stockslab.data.fetch(). An additional 1.5s sleep between symbols avoids
Yahoo rate-limiting.

Defaults:
    1d  → start=2000-01-01
    1h  → period=730d  (yfinance limit)
    5m  → period=60d   (yfinance limit)
"""

import argparse
import sys
import time
import pathlib
import logging
from typing import Optional

# Ensure src/ is on the path when running directly from repo root
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from stockslab.data import UNIVERSE, fetch

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

SLEEP_BETWEEN_SYMBOLS = 1.5  # seconds


def _fmt_row(sym: str, rows: Optional[int], first: str, last: str, status: str) -> str:
    return f"  {sym:<12} {status:<8} rows={rows!s:<8} first={first:<14} last={last}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch and cache OHLCV data.")
    parser.add_argument(
        "--interval",
        required=True,
        choices=["1d", "1h", "5m"],
        help="Bar interval to download.",
    )
    parser.add_argument(
        "--symbols",
        nargs="*",
        default=None,
        help="Symbols to fetch (default: full UNIVERSE).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if cache exists.",
    )
    args = parser.parse_args()

    symbols: list[str] = args.symbols if args.symbols else list(UNIVERSE.keys())
    interval: str = args.interval
    force: bool = args.force

    print(f"\nFetching {len(symbols)} symbols at interval={interval} (force={force})")
    print("-" * 60)

    results: list[tuple[str, str, int, str, str]] = []
    for i, sym in enumerate(symbols, 1):
        try:
            df = fetch(sym, interval, force=force)
            first_date = str(df.index[0].date()) if hasattr(df.index[0], "date") else str(df.index[0])
            last_date = str(df.index[-1].date()) if hasattr(df.index[-1], "date") else str(df.index[-1])
            log.info("[%d/%d] %-12s OK  rows=%-7d %s → %s", i, len(symbols), sym, len(df), first_date, last_date)
            results.append((sym, "OK", len(df), first_date, last_date))
        except Exception as exc:
            log.error("[%d/%d] %-12s FAIL %s", i, len(symbols), sym, exc)
            results.append((sym, "FAIL", 0, "-", str(exc)[:40]))

        if i < len(symbols):
            time.sleep(SLEEP_BETWEEN_SYMBOLS)

    # Summary table
    print("\n" + "=" * 60)
    print(f"{'SYMBOL':<12} {'STATUS':<8} {'ROWS':<8} {'FIRST':<14} LAST")
    print("-" * 60)
    ok_count = 0
    fail_count = 0
    for sym, status, rows, first, last in results:
        rows_str = str(rows) if rows > 0 else "-"
        print(f"{sym:<12} {status:<8} {rows_str:<8} {first:<14} {last}")
        if status == "OK":
            ok_count += 1
        else:
            fail_count += 1

    print("=" * 60)
    print(f"Done: {ok_count} OK, {fail_count} FAIL out of {len(symbols)} symbols.\n")
    sys.exit(0 if fail_count == 0 else 1)


if __name__ == "__main__":
    main()
