"""Backtest engine for the stockslab research lab.

Implements per-symbol event-loop backtesting with strict anti-lookahead semantics.

Engine semantics (frozen API contract):
  1. entry_long[t] True  -> entry at open[t+1] * (1 + slip)   (unless entry_at_open)
  2. In-position bar check order:
       (a) open <= stop         -> gap_stop, exit at open * (1 - slip)
       (b) low  <= stop         -> stop,     exit at stop * (1 - slip)
       (c) high >= target       -> target,   exit at target * (1 - slip)  [stop first]
       (d) exit_long[t-1]       -> signal,   exit at open * (1 - slip)
       (e) time_stop expiry     -> time,     exit at open * (1 - slip)
  3. Trailing stop: after bar close, stop = max(stop, close - trail_atr_mult * atr14)
  4. Exit fills at price * (1 - slip). Still-open at final bar -> eod at close.
  5. One position per symbol; no pyramiding.
  6. entry_at_open: entry_long[t] fills at open[t] * (1+slip) same bar.
  7. r_multiple = (exit - entry) / stop_dist_initial  (slippage included in both)
  8. No entry when stop_dist is NaN or <= 0.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from stockslab.indicators import atr as compute_atr

# Slippage tiers (bps per side)
TIER_BPS: dict[int, int] = {1: 1, 2: 3, 3: 5}


@dataclass
class Trade:
    symbol: str
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    entry: float
    exit: float
    shares: float
    r_multiple: float       # (exit - entry) / stop_dist_initial; slippage on both sides
    pct_return: float       # (exit - entry) / entry; slippage on both sides
    exit_reason: str        # "stop" | "target" | "signal" | "time" | "session" | "gap_stop" | "eod"


def _is_last_bar_of_session(df: pd.DataFrame, i: int) -> bool:
    """Return True if bar i is the last bar of its calendar day."""
    idx = df.index
    current_date = idx[i].date()
    # If next bar exists and is on a different date, this is the last bar
    if i + 1 < len(idx):
        return idx[i + 1].date() != current_date
    # Last bar of the series is always last bar of session
    return True


def run_signal_backtest(
    strategy,
    df: pd.DataFrame,
    symbol: str,
    slippage_bps: int,
) -> list[Trade]:
    """Run a single-symbol signal backtest.

    Parameters
    ----------
    strategy : SignalStrategy
        Strategy instance with a generate() method.
    df : pd.DataFrame
        OHLCV data (columns: open, high, low, close, volume).
    symbol : str
        Symbol name (stored in Trade.symbol).
    slippage_bps : int
        Per-side slippage in basis points (e.g. 3 for 3 bps).

    Returns
    -------
    list[Trade]
        All completed trades (closed positions).
    """
    slip = slippage_bps / 10_000

    # Generate signals
    signals = strategy.generate(df)
    entry_long = signals["entry_long"].values.astype(bool)
    exit_long = signals["exit_long"].values.astype(bool)
    stop_dist_arr = signals["stop_dist"].values.astype(float)

    open_ = df["open"].values.astype(float)
    high_ = df["high"].values.astype(float)
    low_ = df["low"].values.astype(float)
    close_ = df["close"].values.astype(float)
    index = df.index

    # Pre-compute ATR14 for trailing stop (engine computes this itself)
    atr14 = compute_atr(df, n=14).values.astype(float)

    n_bars = len(df)
    trades: list[Trade] = []

    # Position state
    in_position = False
    entry_price = 0.0
    entry_date = None
    stop_price = 0.0
    stop_dist_initial = 0.0
    target_price: float | None = None
    bars_held = 0
    pending_exit = False   # exit_long signal from prior bar
    n_shares = 1.0         # fixed at 1 share (R-based accounting)

    entry_at_open = getattr(strategy, "entry_at_open", False)
    target_r = getattr(strategy, "target_r", None)
    trail_atr_mult = getattr(strategy, "trail_atr_mult", None)
    time_stop_bars = getattr(strategy, "time_stop_bars", None)
    session_exit = getattr(strategy, "session_exit", False)

    for i in range(n_bars):
        o = open_[i]
        h = high_[i]
        l = low_[i]
        c = close_[i]

        if in_position:
            # ---------------------------------------------------------------
            # Check order: gap_stop → stop → target → signal → time → session
            # ---------------------------------------------------------------
            exited = False

            # (a) Gap through stop: open <= stop_price.
            # Skip on the ENTRY bar (bars_held == 0): there is no carried-over
            # prior-bar stop to gap through. The open IS the entry reference, and
            # entry_price = open*(1+slip) > open always, so any stop_dist smaller
            # than open*slip would otherwise fabricate a phantom gap_stop even
            # though the bar never traded below its own open. A genuine intrabar
            # pierce on the entry bar is still caught by branch (b) (low <= stop).
            if bars_held > 0 and o <= stop_price:
                ep = o * (1 - slip)
                r = (ep - entry_price) / stop_dist_initial
                pct = (ep - entry_price) / entry_price
                trades.append(Trade(
                    symbol=symbol,
                    entry_date=entry_date,
                    exit_date=index[i],
                    entry=entry_price,
                    exit=ep,
                    shares=n_shares,
                    r_multiple=r,
                    pct_return=pct,
                    exit_reason="gap_stop",
                ))
                in_position = False
                pending_exit = False
                exited = True

            # (b) Low hits stop (intrabar, open > stop)
            if not exited and l <= stop_price:
                ep = stop_price * (1 - slip)
                r = (ep - entry_price) / stop_dist_initial
                pct = (ep - entry_price) / entry_price
                trades.append(Trade(
                    symbol=symbol,
                    entry_date=entry_date,
                    exit_date=index[i],
                    entry=entry_price,
                    exit=ep,
                    shares=n_shares,
                    r_multiple=r,
                    pct_return=pct,
                    exit_reason="stop",
                ))
                in_position = False
                pending_exit = False
                exited = True

            # (c) High hits target (only if stop not hit first)
            if not exited and target_price is not None and h >= target_price:
                ep = target_price * (1 - slip)
                r = (ep - entry_price) / stop_dist_initial
                pct = (ep - entry_price) / entry_price
                trades.append(Trade(
                    symbol=symbol,
                    entry_date=entry_date,
                    exit_date=index[i],
                    entry=entry_price,
                    exit=ep,
                    shares=n_shares,
                    r_multiple=r,
                    pct_return=pct,
                    exit_reason="target",
                ))
                in_position = False
                pending_exit = False
                exited = True

            # (d) Exit signal from prior bar (fills at current open)
            if not exited and pending_exit:
                ep = o * (1 - slip)
                r = (ep - entry_price) / stop_dist_initial
                pct = (ep - entry_price) / entry_price
                trades.append(Trade(
                    symbol=symbol,
                    entry_date=entry_date,
                    exit_date=index[i],
                    entry=entry_price,
                    exit=ep,
                    shares=n_shares,
                    r_multiple=r,
                    pct_return=pct,
                    exit_reason="signal",
                ))
                in_position = False
                pending_exit = False
                exited = True

            # (e) Time stop: bars_held >= time_stop_bars at open of bar
            if not exited and time_stop_bars is not None and bars_held >= time_stop_bars:
                ep = o * (1 - slip)
                r = (ep - entry_price) / stop_dist_initial
                pct = (ep - entry_price) / entry_price
                trades.append(Trade(
                    symbol=symbol,
                    entry_date=entry_date,
                    exit_date=index[i],
                    entry=entry_price,
                    exit=ep,
                    shares=n_shares,
                    r_multiple=r,
                    pct_return=pct,
                    exit_reason="time",
                ))
                in_position = False
                pending_exit = False
                exited = True

            # (f) Session exit: last bar of day → exit at close
            if not exited and session_exit and _is_last_bar_of_session(df, i):
                ep = c * (1 - slip)
                r = (ep - entry_price) / stop_dist_initial
                pct = (ep - entry_price) / entry_price
                trades.append(Trade(
                    symbol=symbol,
                    entry_date=entry_date,
                    exit_date=index[i],
                    entry=entry_price,
                    exit=ep,
                    shares=n_shares,
                    r_multiple=r,
                    pct_return=pct,
                    exit_reason="session",
                ))
                in_position = False
                pending_exit = False
                exited = True

            # Final bar: eod exit if still in position
            if not exited and i == n_bars - 1:
                ep = c * (1 - slip)
                r = (ep - entry_price) / stop_dist_initial
                pct = (ep - entry_price) / entry_price
                trades.append(Trade(
                    symbol=symbol,
                    entry_date=entry_date,
                    exit_date=index[i],
                    entry=entry_price,
                    exit=ep,
                    shares=n_shares,
                    r_multiple=r,
                    pct_return=pct,
                    exit_reason="eod",
                ))
                in_position = False
                pending_exit = False
                exited = True

            # Post-bar: update trailing stop and pending exit flag
            if in_position:
                bars_held += 1
                # Update trailing stop after close (ratchet up only)
                if trail_atr_mult is not None and not math.isnan(atr14[i]):
                    new_stop = c - trail_atr_mult * atr14[i]
                    stop_price = max(stop_price, new_stop)
                # Set pending_exit for next bar if exit signal on this bar
                if exit_long[i]:
                    pending_exit = True

        # ---------------------------------------------------------------
        # Entry logic (only when not in position after exit checks)
        # ---------------------------------------------------------------
        if not in_position:
            if entry_at_open:
                # entry_at_open: fill at open[i] if entry_long[i]
                sd = stop_dist_arr[i]
                if entry_long[i] and not (math.isnan(sd) or sd <= 0.0):
                    ep_price = o * (1 + slip)
                    entry_price = ep_price
                    stop_dist_initial = sd
                    stop_price = ep_price - sd
                    target_price = (ep_price + target_r * sd) if target_r is not None else None
                    entry_date = index[i]
                    bars_held = 1
                    pending_exit = False
                    in_position = True

                    # Immediately check stop/target/session on same bar
                    # (since we entered mid-bar at open, we still evaluate the rest of the bar)
                    exited = False

                    # gap_stop check: open is the entry, open == stop means gap
                    # After entry_at_open, stop = entry - stop_dist; o > stop always
                    # (open can't be below stop we just set based on open+slip)

                    # Stop intrabar
                    if not exited and l <= stop_price:
                        ep = stop_price * (1 - slip)
                        r = (ep - entry_price) / stop_dist_initial
                        pct = (ep - entry_price) / entry_price
                        trades.append(Trade(
                            symbol=symbol,
                            entry_date=entry_date,
                            exit_date=index[i],
                            entry=entry_price,
                            exit=ep,
                            shares=n_shares,
                            r_multiple=r,
                            pct_return=pct,
                            exit_reason="stop",
                        ))
                        in_position = False
                        exited = True

                    # Target intrabar
                    if not exited and target_price is not None and h >= target_price:
                        ep = target_price * (1 - slip)
                        r = (ep - entry_price) / stop_dist_initial
                        pct = (ep - entry_price) / entry_price
                        trades.append(Trade(
                            symbol=symbol,
                            entry_date=entry_date,
                            exit_date=index[i],
                            entry=entry_price,
                            exit=ep,
                            shares=n_shares,
                            r_multiple=r,
                            pct_return=pct,
                            exit_reason="target",
                        ))
                        in_position = False
                        exited = True

                    # Time stop on the ENTRY bar (gap_fade same-bar round trip).
                    # entry_at_open counts the entry bar as bar 1 (bars_held == 1),
                    # so time_stop_bars <= 1 closes at THIS bar's CLOSE, reason
                    # "time" — i.e. buy the open, sell the same close. Without this,
                    # the position leaked into the next bar and exited at the wrong
                    # (next-open) price as an unintended overnight hold.
                    if not exited and time_stop_bars is not None and bars_held >= time_stop_bars:
                        ep = c * (1 - slip)
                        r = (ep - entry_price) / stop_dist_initial
                        pct = (ep - entry_price) / entry_price
                        trades.append(Trade(
                            symbol=symbol,
                            entry_date=entry_date,
                            exit_date=index[i],
                            entry=entry_price,
                            exit=ep,
                            shares=n_shares,
                            r_multiple=r,
                            pct_return=pct,
                            exit_reason="time",
                        ))
                        in_position = False
                        exited = True

                    # Session exit on same bar
                    if not exited and session_exit and _is_last_bar_of_session(df, i):
                        ep = c * (1 - slip)
                        r = (ep - entry_price) / stop_dist_initial
                        pct = (ep - entry_price) / entry_price
                        trades.append(Trade(
                            symbol=symbol,
                            entry_date=entry_date,
                            exit_date=index[i],
                            entry=entry_price,
                            exit=ep,
                            shares=n_shares,
                            r_multiple=r,
                            pct_return=pct,
                            exit_reason="session",
                        ))
                        in_position = False
                        exited = True

                    # eod on final bar
                    if not exited and i == n_bars - 1:
                        ep = c * (1 - slip)
                        r = (ep - entry_price) / stop_dist_initial
                        pct = (ep - entry_price) / entry_price
                        trades.append(Trade(
                            symbol=symbol,
                            entry_date=entry_date,
                            exit_date=index[i],
                            entry=entry_price,
                            exit=ep,
                            shares=n_shares,
                            r_multiple=r,
                            pct_return=pct,
                            exit_reason="eod",
                        ))
                        in_position = False
                        exited = True

                    # Post-bar trailing stop update for entry_at_open
                    if in_position:
                        if trail_atr_mult is not None and not math.isnan(atr14[i]):
                            new_stop = c - trail_atr_mult * atr14[i]
                            stop_price = max(stop_price, new_stop)
                        if exit_long[i]:
                            pending_exit = True

            else:
                # Standard entry: entry_long[i] → fill at open[i+1]
                sd = stop_dist_arr[i]
                if entry_long[i] and not (math.isnan(sd) or sd <= 0.0) and i + 1 < n_bars:
                    ep_price = open_[i + 1] * (1 + slip)
                    entry_price = ep_price
                    stop_dist_initial = sd
                    stop_price = ep_price - sd
                    target_price = (ep_price + target_r * sd) if target_r is not None else None
                    entry_date = index[i + 1]
                    bars_held = 1
                    pending_exit = False
                    in_position = True

                    # The next bar (i+1) is processed in the next loop iteration.
                    # However we entered in the context of bar i+1's open, so we need
                    # to process bar i+1 as an in-position bar immediately.
                    # We do this by advancing i to i+1 and re-doing the in-position logic.
                    # Instead: the loop naturally increments i, so bar i+1 will be processed
                    # as an in-position bar. But we need to handle the case where i+1 == n_bars-1.
                    # The entry is recorded at index[i+1]; the loop processes bar i+1 next.
                    # bars_held is set to 1 BEFORE bar i+1 is processed as in-position.
                    # Actually, bars_held should be 0 going into bar i+1 (first in-position bar),
                    # then incremented after bar i+1 completes if still open.
                    # Let's use bars_held=0 at entry; the in-position block increments to 1 post-bar.
                    bars_held = 0

    return trades


def run_rotation_backtest(strategy, panel: dict, slippage_bps_map: dict) -> list[Trade]:
    """Run a rotation-style backtest across a panel of symbols.

    Semantics (frozen API contract):
    - strategy.target_holdings(panel, dates) returns a DataFrame of 0/1 membership
      indexed by rebalance dates (subset of the union of all symbol dates).
    - At each rebalance date d, compare the new target to the current holdings:
        * Add  (0 -> 1): enter at the OPEN of the NEXT bar after d, with buy slip.
        * Drop (1 -> 0): exit  at the OPEN of the NEXT bar after d, with sell slip.
        * Held (1 -> 1): no action (position continues untouched).
    - Each add results in exactly one Trade whose exit is triggered at the next drop
      rebalance or at end-of-data (eod).
    - r_multiple = pct_return / 0.10  (10%-notional R proxy: a 10% move = 1R;
      this is a sizing-independent ranking anchor for rotation strategies, which
      do not use an explicit $ stop distance).
    - pct_return = (exit_price - entry_price) / entry_price, slippage on both sides.
    - exit_reason: "rotation" when exited at a rebalance drop; "eod" when data ends
      while position is still held.
    - If a symbol is added at the last rebalance date and no next bar exists, no Trade
      is emitted (cannot fill).

    Parameters
    ----------
    strategy : RotationStrategy
        Strategy instance with target_holdings().
    panel : dict[str, pd.DataFrame]
        Symbol -> OHLCV DataFrame.
    slippage_bps_map : dict[str, int]
        Symbol -> per-side slippage in basis points.

    Returns
    -------
    list[Trade]
        One Trade per (symbol, holding period) pair.
    """
    # Build the union of all dates across the panel
    all_dates: pd.DatetimeIndex = pd.DatetimeIndex(
        sorted(set().union(*[set(df.index) for df in panel.values()]))
    )

    # Get target holdings from the strategy
    holdings_df: pd.DataFrame = strategy.target_holdings(panel, all_dates)
    # holdings_df: index = rebalance dates, columns = symbols, values = 0/1

    trades: list[Trade] = []

    # Track current open positions per symbol:
    #   pending_entry[symbol] = (entry_date, entry_price, slippage_bps) or None
    pending_entries: dict[str, tuple[pd.Timestamp, float, float] | None] = {}

    # Current membership state (last known): symbol -> 0|1
    current_holdings: dict[str, int] = {sym: 0 for sym in holdings_df.columns}

    # Process rebalances in chronological order
    rebalance_dates = holdings_df.index.sort_values()

    for reb_date in rebalance_dates:
        new_row = holdings_df.loc[reb_date]

        # For each symbol in the holdings matrix, determine action
        for sym in holdings_df.columns:
            new_val = int(new_row[sym])
            old_val = current_holdings.get(sym, 0)

            df = panel.get(sym)
            if df is None:
                continue

            slip_bps = slippage_bps_map.get(sym, 5)
            slip = slip_bps / 10_000

            if old_val == 0 and new_val == 1:
                # ADD: find the next bar after reb_date, enter at its open
                future = df.index[df.index > reb_date]
                if len(future) == 0:
                    # No fill bar available — skip
                    current_holdings[sym] = 1  # still mark as intended-hold
                    pending_entries[sym] = None  # sentinel: added but unfillable
                    continue
                fill_date = future[0]
                entry_price = float(df.loc[fill_date, "open"]) * (1 + slip)
                pending_entries[sym] = (fill_date, entry_price, slip_bps)
                current_holdings[sym] = 1

            elif old_val == 1 and new_val == 0:
                # DROP: find the next bar after reb_date, exit at its open
                entry_info = pending_entries.pop(sym, None)
                if entry_info is None:
                    # Was added on last bar (unfillable) — nothing to close
                    current_holdings[sym] = 0
                    continue
                entry_date, entry_price, entry_slip_bps = entry_info
                entry_slip = entry_slip_bps / 10_000

                future = df.index[df.index > reb_date]
                if len(future) == 0:
                    # No exit bar: eod at last close
                    exit_date = df.index[-1]
                    exit_price = float(df.loc[exit_date, "close"]) * (1 - entry_slip)
                    reason = "eod"
                else:
                    exit_date = future[0]
                    exit_price = float(df.loc[exit_date, "open"]) * (1 - entry_slip)
                    reason = "rotation"

                pct_return = (exit_price - entry_price) / entry_price
                # r_multiple = pct_return / 0.10 (10%-notional R proxy:
                # a 10% move on the position equates to 1R in the ranking metric;
                # rotation strategies have no explicit $ stop, so we use this
                # notional anchor to keep r_multiple comparable across signal
                # and rotation strategies for gate evaluation purposes.)
                r_multiple = pct_return / 0.10

                trades.append(Trade(
                    symbol=sym,
                    entry_date=entry_date,
                    exit_date=exit_date,
                    entry=entry_price,
                    exit=exit_price,
                    shares=1.0,
                    r_multiple=r_multiple,
                    pct_return=pct_return,
                    exit_reason=reason,
                ))
                current_holdings[sym] = 0

            # else: held (1->1) or unaffected (0->0): no action

    # After all rebalances: any symbols still open get an eod exit at their last close
    for sym, entry_info in list(pending_entries.items()):
        if entry_info is None:
            continue  # unfillable add, skip
        if current_holdings.get(sym, 0) != 1:
            continue  # already closed

        df = panel.get(sym)
        if df is None:
            continue

        entry_date, entry_price, entry_slip_bps = entry_info
        entry_slip = entry_slip_bps / 10_000

        exit_date = df.index[-1]
        exit_price = float(df.loc[exit_date, "close"]) * (1 - entry_slip)

        pct_return = (exit_price - entry_price) / entry_price
        r_multiple = pct_return / 0.10

        trades.append(Trade(
            symbol=sym,
            entry_date=entry_date,
            exit_date=exit_date,
            entry=entry_price,
            exit=exit_price,
            shares=1.0,
            r_multiple=r_multiple,
            pct_return=pct_return,
            exit_reason="eod",
        ))

    return trades


def run_universe(
    strategy,
    panel: dict[str, pd.DataFrame],
    tiers: dict[str, int],
) -> list[Trade]:
    """Run a strategy across a panel of symbols.

    Sets strategy.context = panel before per-symbol runs (for cross-frame strategies).

    Parameters
    ----------
    strategy : SignalStrategy
        Strategy instance.
    panel : dict[str, pd.DataFrame]
        Symbol -> OHLCV DataFrame.
    tiers : dict[str, int]
        Symbol -> liquidity tier (1, 2, or 3).

    Returns
    -------
    list[Trade]
        All trades from all symbols, concatenated.
    """
    # Set context for cross-frame strategies (e.g. levered_etf_meanrev)
    strategy.context = panel

    all_trades: list[Trade] = []
    for symbol, df in panel.items():
        tier = tiers.get(symbol, 3)
        slippage_bps = TIER_BPS[tier]
        symbol_trades = run_signal_backtest(strategy, df, symbol, slippage_bps)
        all_trades.extend(symbol_trades)

    return all_trades
