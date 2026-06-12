"""Metrics and gate evaluation for the stockslab backtest lab.

Frozen API contract signatures (do not change names or return types):

  profit_factor(trades) -> float
  win_rate(trades) -> float
  summarize(trades) -> dict
  equity_curve(trades, risk_frac=0.01) -> pd.Series
  max_drawdown(curve) -> float
  phase1_gate(s: dict) -> tuple[bool, list[str]]
  phase2_oos(s: dict) -> tuple[bool, list[str]]

All R-based functions use the `r_multiple` field of Trade objects.
PF is inf-safe: no losers → inf (by convention; gate handles this gracefully).
Equity curve: compounded fixed-fraction (default 1% risk), sorted by exit_date.
"""

from __future__ import annotations

import math
from collections import Counter

import pandas as pd


# ---------------------------------------------------------------------------
# profit_factor
# ---------------------------------------------------------------------------

def profit_factor(trades) -> float:
    """Sum of winning R multiples divided by absolute sum of losing R multiples.

    Inf-safe: if there are no losers (denominator == 0) returns math.inf.
    Returns 0.0 if there are no winners.
    """
    gross_profit = sum(t.r_multiple for t in trades if t.r_multiple > 0)
    gross_loss = abs(sum(t.r_multiple for t in trades if t.r_multiple < 0))
    if gross_loss == 0.0:
        return math.inf
    return gross_profit / gross_loss


# ---------------------------------------------------------------------------
# win_rate
# ---------------------------------------------------------------------------

def win_rate(trades) -> float:
    """Fraction of trades with r_multiple > 0. Returns 0.0 for empty input."""
    if not trades:
        return 0.0
    n_wins = sum(1 for t in trades if t.r_multiple > 0)
    return n_wins / len(trades)


# ---------------------------------------------------------------------------
# equity_curve
# ---------------------------------------------------------------------------

def equity_curve(trades, risk_frac: float = 0.01) -> pd.Series:
    """Compound an equity curve from a list of trades.

    Starting equity = 1.0. Each trade multiplies equity by:
        (1 + r_multiple * risk_frac)

    Trades are sorted by exit_date before compounding. The returned Series
    is indexed by exit_date (pd.Timestamp) in ascending order.

    Parameters
    ----------
    trades : list[Trade]
    risk_frac : float
        Fraction of equity risked per trade (default 0.01 = 1%).

    Returns
    -------
    pd.Series
        Equity values after each trade, indexed by exit_date.
    """
    if not trades:
        return pd.Series([], dtype=float)

    # Sort by exit_date, with a stable secondary key so the curve (and thus
    # max_drawdown) is deterministic regardless of symbol-iteration order among
    # trades sharing an exit_date.
    sorted_trades = sorted(trades, key=lambda t: (t.exit_date, t.entry_date, t.symbol))
    equity = 1.0
    dates = []
    values = []
    for t in sorted_trades:
        equity *= 1.0 + t.r_multiple * risk_frac
        dates.append(t.exit_date)
        values.append(equity)

    return pd.Series(values, index=pd.DatetimeIndex(dates))


# ---------------------------------------------------------------------------
# max_drawdown
# ---------------------------------------------------------------------------

def max_drawdown(curve: pd.Series) -> float:
    """Maximum peak-to-trough drawdown of an equity curve.

    Returns the drawdown as a positive fraction (0.20 = 20% drawdown).
    Returns 0.0 for empty or single-element curves.

    Parameters
    ----------
    curve : pd.Series
        Equity values in chronological order.

    Returns
    -------
    float
        Maximum drawdown as a non-negative fraction.
    """
    if len(curve) <= 1:
        return 0.0

    values = curve.values.astype(float)
    running_max = values[0]
    max_dd = 0.0
    for v in values:
        if v > running_max:
            running_max = v
        dd = (running_max - v) / running_max
        if dd > max_dd:
            max_dd = dd
    return max_dd


# ---------------------------------------------------------------------------
# summarize
# ---------------------------------------------------------------------------

def summarize(trades) -> dict:
    """Compute a summary statistics dictionary from a list of trades.

    Returns
    -------
    dict with keys:
        pf              : float  — profit factor
        wr              : float  — win rate
        n               : int    — trade count
        avg_r           : float  — mean r_multiple
        med_hold_bars   : float  — median holding period in calendar days
                                   (exit_date - entry_date).days; use 0 if no trades
        max_dd_1pct     : float  — max drawdown of equity curve at 1% risk
        exit_reason_counts : dict[str, int]
    """
    # Fail loud on corrupt data: a non-finite r_multiple (NaN/inf) would be
    # silently dropped from profit_factor and would poison the equity curve to
    # NaN. Surface it as an error rather than reporting misleading stats.
    bad = [t for t in trades if not math.isfinite(t.r_multiple)]
    if bad:
        raise ValueError(
            f"summarize() received {len(bad)} trade(s) with non-finite r_multiple "
            f"(e.g. symbol={bad[0].symbol}, exit_date={bad[0].exit_date}); "
            "this indicates upstream data/engine corruption."
        )

    pf = profit_factor(trades)
    wr = win_rate(trades)
    n = len(trades)
    avg_r = sum(t.r_multiple for t in trades) / n if n > 0 else 0.0

    if n > 0:
        hold_days = [(t.exit_date - t.entry_date).days for t in trades]
        sorted_days = sorted(hold_days)
        mid = n // 2
        if n % 2 == 0:
            med_hold_bars = (sorted_days[mid - 1] + sorted_days[mid]) / 2.0
        else:
            med_hold_bars = float(sorted_days[mid])
    else:
        med_hold_bars = 0.0

    curve = equity_curve(trades, risk_frac=0.01)
    max_dd_1pct = max_drawdown(curve)

    exit_reason_counts = dict(Counter(t.exit_reason for t in trades))

    return {
        "pf": pf,
        "wr": wr,
        "n": n,
        "avg_r": avg_r,
        "med_hold_bars": med_hold_bars,
        "max_dd_1pct": max_dd_1pct,
        "exit_reason_counts": exit_reason_counts,
    }


# ---------------------------------------------------------------------------
# phase1_gate
# ---------------------------------------------------------------------------

def phase1_gate(s: dict) -> tuple[bool, list[str]]:
    """Evaluate Phase-1 in-sample gate: PF > 1.3 AND n >= 500.

    Parameters
    ----------
    s : dict
        Summary dict as returned by summarize(), must have keys "pf" and "n".

    Returns
    -------
    (passed: bool, reasons: list[str])
        If passed, reasons is an empty list.
        If failed, reasons contains one string per failing condition.
    """
    reasons: list[str] = []
    pf_val = s["pf"]
    n_val = s["n"]

    # A non-finite PF (inf) means zero losing trades over the whole sample —
    # over a 500+ trade in-sample window that is almost certainly an upstream
    # bug (sign error, fill artifact masking losers), not a real edge. Do NOT
    # auto-pass it; flag as suspicious so it gets investigated, not promoted.
    if not math.isfinite(pf_val):
        reasons.append(
            f"pf is non-finite ({pf_val}) — zero losers over {n_val} trades is "
            "suspicious (likely an upstream bug, not an edge); not auto-passed"
        )
    elif not (pf_val > 1.3):
        reasons.append(f"pf {pf_val:.4f} <= 1.3 (required pf > 1.3)")
    if not (n_val >= 500):
        reasons.append(f"n {n_val} < 500 (required n >= 500)")

    return (len(reasons) == 0, reasons)


# ---------------------------------------------------------------------------
# phase2_oos
# ---------------------------------------------------------------------------

def phase2_oos(s: dict) -> tuple[bool, list[str]]:
    """Evaluate Phase-2 out-of-sample gate: PF > 1.15.

    Parameters
    ----------
    s : dict
        Summary dict as returned by summarize(), must have key "pf".

    Returns
    -------
    (passed: bool, reasons: list[str])
        If passed, reasons is an empty list.
        If failed, reasons contains one string per failing condition.
    """
    reasons: list[str] = []
    pf_val = s["pf"]

    if not (pf_val > 1.15):
        reasons.append(f"pf {pf_val:.4f} <= 1.15 (required pf > 1.15)")

    return (len(reasons) == 0, reasons)
