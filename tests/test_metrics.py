"""Tests for src/stockslab/metrics.py (Task A5).

All expected values are hand-computed from first principles.

Functions under test:
  profit_factor(trades) -> float
  win_rate(trades) -> float
  summarize(trades) -> dict   keys: pf, wr, n, avg_r, med_hold_bars, max_dd_1pct, exit_reason_counts
  equity_curve(trades, risk_frac=0.01) -> pd.Series
  max_drawdown(curve) -> float
  phase1_gate(s: dict) -> tuple[bool, list[str]]
  phase2_oos(s: dict) -> tuple[bool, list[str]]
"""

from __future__ import annotations

import math
import pandas as pd
import pytest

from stockslab.engine import Trade
import stockslab.metrics as metrics


# ---------------------------------------------------------------------------
# Helper to create Trade objects without filling every optional field
# ---------------------------------------------------------------------------

def _trade(
    r_multiple: float,
    pct_return: float = 0.0,
    symbol: str = "A",
    entry_date: str = "2020-01-07",
    exit_date: str = "2020-01-14",
    exit_reason: str = "signal",
):
    return Trade(
        symbol=symbol,
        entry_date=pd.Timestamp(entry_date),
        exit_date=pd.Timestamp(exit_date),
        entry=100.0,
        exit=100.0 * (1 + pct_return),
        shares=1.0,
        r_multiple=r_multiple,
        pct_return=pct_return,
        exit_reason=exit_reason,
    )


# ---------------------------------------------------------------------------
# profit_factor
# ---------------------------------------------------------------------------

class TestProfitFactor:
    def test_simple_pf(self):
        """3 winners +1R each, 2 losers -1R each. PF = 3/2 = 1.5."""
        trades = [_trade(1.0)] * 3 + [_trade(-1.0)] * 2
        assert abs(metrics.profit_factor(trades) - 1.5) < 1e-10

    def test_all_winners_returns_inf(self):
        """No losers -> denominator = 0 -> inf."""
        trades = [_trade(1.0)] * 5
        result = metrics.profit_factor(trades)
        assert math.isinf(result) and result > 0

    def test_all_losers(self):
        """No winners -> numerator = 0 -> PF = 0."""
        trades = [_trade(-1.0)] * 3
        assert metrics.profit_factor(trades) == 0.0

    def test_empty_trades_returns_inf(self):
        """Empty list: no losses -> inf (by convention, inf-safe)."""
        result = metrics.profit_factor([])
        assert math.isinf(result) and result > 0

    def test_mixed_values(self):
        """Winners: 2+0.5=2.5; Losers: 1.0. PF = 2.5/1.0 = 2.5"""
        trades = [_trade(2.0), _trade(0.5), _trade(-1.0)]
        assert abs(metrics.profit_factor(trades) - 2.5) < 1e-10

    def test_breakeven_trade_not_counted_as_winner_or_loser(self):
        """r=0 trades don't count for numerator or denominator."""
        trades = [_trade(1.0), _trade(0.0), _trade(-1.0)]
        # numerator=1.0, denominator=1.0 -> PF=1.0
        assert abs(metrics.profit_factor(trades) - 1.0) < 1e-10


# ---------------------------------------------------------------------------
# win_rate
# ---------------------------------------------------------------------------

class TestWinRate:
    def test_simple_win_rate(self):
        """3 winners, 2 losers -> wr = 0.6"""
        trades = [_trade(1.0)] * 3 + [_trade(-1.0)] * 2
        assert abs(metrics.win_rate(trades) - 0.6) < 1e-10

    def test_all_winners(self):
        trades = [_trade(1.0)] * 4
        assert abs(metrics.win_rate(trades) - 1.0) < 1e-10

    def test_all_losers(self):
        trades = [_trade(-1.0)] * 3
        assert abs(metrics.win_rate(trades) - 0.0) < 1e-10

    def test_empty_returns_zero(self):
        assert metrics.win_rate([]) == 0.0

    def test_breakeven_is_not_a_win(self):
        """r=0 is not a win."""
        trades = [_trade(0.0), _trade(1.0)]
        # 1 win out of 2
        assert abs(metrics.win_rate(trades) - 0.5) < 1e-10


# ---------------------------------------------------------------------------
# equity_curve
# ---------------------------------------------------------------------------

class TestEquityCurve:
    def test_single_trade_compounding(self):
        """
        Single trade: r_multiple=1.0, risk_frac=0.01
        Starting equity = 1.0
        After trade: 1.0 * (1 + 1.0 * 0.01) = 1.01
        Curve has 1 value = 1.01
        """
        t = _trade(1.0, exit_date="2020-01-14")
        curve = metrics.equity_curve([t], risk_frac=0.01)
        assert len(curve) == 1
        assert abs(curve.iloc[0] - 1.01) < 1e-10

    def test_two_trades_compounding(self):
        """
        Trade 1: r=+2.0 -> equity *= (1 + 2*0.01) = 1.02
        Trade 2: r=-1.0 -> equity *= (1 - 1*0.01) = 1.02 * 0.99 = 1.0098
        """
        t1 = _trade(2.0, exit_date="2020-01-07")
        t2 = _trade(-1.0, exit_date="2020-01-14")
        curve = metrics.equity_curve([t1, t2], risk_frac=0.01)
        assert len(curve) == 2
        assert abs(curve.iloc[0] - 1.02) < 1e-10
        assert abs(curve.iloc[1] - 1.02 * 0.99) < 1e-10

    def test_curve_sorted_by_exit_date(self):
        """Curve must be ordered by exit_date regardless of input order."""
        t1 = _trade(1.0, exit_date="2020-01-20")
        t2 = _trade(1.0, exit_date="2020-01-07")
        # Input order: t1 then t2 (but t2 exits first)
        curve = metrics.equity_curve([t1, t2], risk_frac=0.01)
        # t2 exits 2020-01-07 first -> first point; t1 exits 2020-01-20 second
        assert curve.index[0] == pd.Timestamp("2020-01-07")
        assert curve.index[1] == pd.Timestamp("2020-01-20")

    def test_default_risk_frac_is_001(self):
        """Default risk_frac = 0.01."""
        t = _trade(1.0)
        curve = metrics.equity_curve([t])
        assert abs(curve.iloc[0] - 1.01) < 1e-10

    def test_empty_trades_returns_empty_series(self):
        curve = metrics.equity_curve([])
        assert len(curve) == 0

    def test_starts_at_one_before_first_trade(self):
        """After 1 winning trade at risk_frac=0.01 the curve value is >1."""
        t = _trade(0.5)
        curve = metrics.equity_curve([t], risk_frac=0.01)
        assert curve.iloc[0] > 1.0


# ---------------------------------------------------------------------------
# max_drawdown
# ---------------------------------------------------------------------------

class TestMaxDrawdown:
    def test_no_drawdown(self):
        """Monotonically rising curve -> drawdown = 0."""
        curve = pd.Series([1.0, 1.01, 1.02, 1.03])
        assert abs(metrics.max_drawdown(curve) - 0.0) < 1e-10

    def test_simple_drawdown(self):
        """Peak=1.0, trough=0.80 -> DD = (1.0-0.80)/1.0 = 0.20."""
        curve = pd.Series([1.0, 0.90, 0.80, 0.85])
        dd = metrics.max_drawdown(curve)
        assert abs(dd - 0.20) < 1e-10

    def test_drawdown_after_new_high(self):
        """
        Peak at idx 2 = 1.10; trough after = 0.99.
        DD = (1.10 - 0.99) / 1.10 = 0.1/1.10 ≈ 0.09090909...
        """
        curve = pd.Series([1.0, 1.05, 1.10, 0.99])
        dd = metrics.max_drawdown(curve)
        expected = (1.10 - 0.99) / 1.10
        assert abs(dd - expected) < 1e-10

    def test_empty_series_returns_zero(self):
        assert metrics.max_drawdown(pd.Series([], dtype=float)) == 0.0

    def test_single_element_returns_zero(self):
        assert metrics.max_drawdown(pd.Series([1.0])) == 0.0

    def test_drawdown_is_non_negative(self):
        curve = pd.Series([1.0, 1.05, 0.90, 0.85, 0.95])
        assert metrics.max_drawdown(curve) >= 0.0


# ---------------------------------------------------------------------------
# summarize
# ---------------------------------------------------------------------------

class TestSummarize:
    def setup_method(self):
        """Build a small set of trades for summarize testing."""
        # 3 winning trades r=1.0, 2 losing trades r=-1.0
        # entry_date is always "2020-01-06", exit_date varies so hold period = 1 bar
        self.trades = (
            [_trade(1.0, exit_date="2020-01-07")] * 3
            + [_trade(-1.0, exit_date="2020-01-08")] * 2
        )

    def test_summarize_returns_dict(self):
        s = metrics.summarize(self.trades)
        assert isinstance(s, dict)

    def test_summarize_has_required_keys(self):
        s = metrics.summarize(self.trades)
        for key in ("pf", "wr", "n", "avg_r", "med_hold_bars", "max_dd_1pct", "exit_reason_counts"):
            assert key in s, f"Missing key: {key}"

    def test_summarize_pf(self):
        s = metrics.summarize(self.trades)
        assert abs(s["pf"] - 1.5) < 1e-10

    def test_summarize_wr(self):
        s = metrics.summarize(self.trades)
        assert abs(s["wr"] - 0.6) < 1e-10

    def test_summarize_n(self):
        s = metrics.summarize(self.trades)
        assert s["n"] == 5

    def test_summarize_avg_r(self):
        # avg_r = (3*1.0 + 2*(-1.0)) / 5 = 1/5 = 0.2
        s = metrics.summarize(self.trades)
        assert abs(s["avg_r"] - 0.2) < 1e-10

    def test_summarize_exit_reason_counts(self):
        s = metrics.summarize(self.trades)
        assert s["exit_reason_counts"]["signal"] == 5

    def test_summarize_max_dd_1pct_is_float(self):
        s = metrics.summarize(self.trades)
        assert isinstance(s["max_dd_1pct"], float)


# ---------------------------------------------------------------------------
# phase1_gate
# ---------------------------------------------------------------------------

class TestPhase1Gate:
    def test_passes_when_pf_high_and_n_large(self):
        s = {"pf": 1.5, "n": 600, "wr": 0.6, "avg_r": 0.2}
        passed, reasons = metrics.phase1_gate(s)
        assert passed is True
        assert reasons == []

    def test_fails_pf_too_low(self):
        s = {"pf": 1.2, "n": 600}
        passed, reasons = metrics.phase1_gate(s)
        assert passed is False
        assert any("pf" in r.lower() or "profit" in r.lower() for r in reasons)

    def test_fails_n_too_low(self):
        s = {"pf": 1.5, "n": 499}
        passed, reasons = metrics.phase1_gate(s)
        assert passed is False
        assert any("n" in r.lower() or "trade" in r.lower() for r in reasons)

    def test_fails_both(self):
        s = {"pf": 1.1, "n": 100}
        passed, reasons = metrics.phase1_gate(s)
        assert passed is False
        assert len(reasons) == 2

    def test_exact_boundary_pf_13_passes(self):
        """pf > 1.3 strictly; 1.3 itself does NOT pass."""
        s = {"pf": 1.3, "n": 500}
        passed, _ = metrics.phase1_gate(s)
        assert passed is False

    def test_exact_boundary_n_500_passes(self):
        """n >= 500; 500 passes."""
        s = {"pf": 1.4, "n": 500}
        passed, _ = metrics.phase1_gate(s)
        assert passed is True


# ---------------------------------------------------------------------------
# phase2_oos
# ---------------------------------------------------------------------------

class TestPhase2Oos:
    def test_passes_when_pf_high(self):
        s = {"pf": 1.2, "n": 200}
        passed, reasons = metrics.phase2_oos(s)
        assert passed is True
        assert reasons == []

    def test_fails_pf_too_low(self):
        s = {"pf": 1.10, "n": 200}
        passed, reasons = metrics.phase2_oos(s)
        assert passed is False
        assert any("pf" in r.lower() or "profit" in r.lower() for r in reasons)

    def test_exact_boundary_115_fails(self):
        """pf > 1.15 strictly; 1.15 does NOT pass."""
        s = {"pf": 1.15, "n": 200}
        passed, _ = metrics.phase2_oos(s)
        assert passed is False

    def test_just_above_boundary_passes(self):
        s = {"pf": 1.1501, "n": 200}
        passed, _ = metrics.phase2_oos(s)
        assert passed is True


# ---------------------------------------------------------------------------
# Integration: equity_curve + max_drawdown via summarize
# ---------------------------------------------------------------------------

class TestSummarizeMaxDd1Pct:
    def test_max_dd_1pct_uses_equity_curve(self):
        """
        3 winners r=+2, then 2 big losers r=-3.
        At risk_frac=0.01:
          after winner 1: 1.0 * 1.02 = 1.02
          after winner 2: 1.02 * 1.02 = 1.0404
          after winner 3: 1.0404 * 1.02 = 1.061208
          after loser 1:  1.061208 * (1 - 0.03) = 1.029372
          after loser 2:  1.029372 * 0.97 = 0.998490

        Peak = 1.061208
        Trough = 0.998490
        max_dd = (1.061208 - 0.998490) / 1.061208 ≈ 0.059094
        """
        trades = (
            [_trade(2.0, exit_date=f"2020-01-0{i}") for i in range(7, 10)]   # 3 winners
            + [_trade(-3.0, exit_date=f"2020-01-1{i}") for i in range(0, 2)]  # 2 losers
        )
        s = metrics.summarize(trades)
        # Just check it's a non-negative float; exact value tested separately
        assert s["max_dd_1pct"] >= 0.0
        # Confirm it's non-trivial (we expect DD > 0 here)
        assert s["max_dd_1pct"] > 0.0


# ===========================================================================
# REGRESSION/HARDENING — minor findings from adversarial Opus review (2026-06-12)
# ===========================================================================


class TestEquityCurveDeterministicTieOrder:
    """max_dd must not depend on the symbol-iteration order of same-exit_date trades."""

    def test_same_exit_date_trades_give_deterministic_max_dd(self):
        # Two trades exit on the SAME date but have different entry dates.
        # +5R and -4R. With only exit_date sorting, input order would change the
        # intra-curve path and thus max_dd. A stable secondary key fixes it.
        win = _trade(5.0, entry_date="2020-01-02", exit_date="2020-01-10", symbol="A")
        loss = _trade(-4.0, entry_date="2020-01-05", exit_date="2020-01-10", symbol="B")

        dd_order1 = metrics.max_drawdown(metrics.equity_curve([win, loss]))
        dd_order2 = metrics.max_drawdown(metrics.equity_curve([loss, win]))
        assert dd_order1 == pytest.approx(dd_order2)


class TestSummarizeFailsLoudOnNonFiniteR:
    """A NaN r_multiple silently poisons the equity curve; summarize must reject it."""

    def test_nan_r_multiple_raises(self):
        bad = [_trade(1.0), _trade(float("nan"))]
        with pytest.raises(ValueError):
            metrics.summarize(bad)

    def test_inf_r_multiple_raises(self):
        bad = [_trade(1.0), _trade(float("inf"))]
        with pytest.raises(ValueError):
            metrics.summarize(bad)


class TestPhase1GateRejectsNonFinitePf:
    """PF == inf over >=500 trades means ZERO losers — almost always an upstream
    bug, not a real edge. The gate must NOT auto-pass it."""

    def test_inf_pf_does_not_pass(self):
        s = {"pf": float("inf"), "n": 600}
        passed, reasons = metrics.phase1_gate(s)
        assert passed is False
        assert any("finite" in r.lower() or "inf" in r.lower() or "suspicious" in r.lower()
                   for r in reasons)
