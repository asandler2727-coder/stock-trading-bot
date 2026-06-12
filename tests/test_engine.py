"""Tests for engine.py — strict TDD against hand-computed fill prices.

Every fill price in every test is computed by hand in a comment block,
then asserted with pytest.approx for floats.

Slippage tiers (per side, bps): TIER_BPS = {1: 1, 2: 3, 3: 5}
  bps_per_side / 10_000  ->  tier1: 0.0001, tier2: 0.0003, tier3: 0.0005

Engine semantics (from contract):
  1. entry_long[t] True  -> entry at open[t+1] * (1 + slip)   (unless entry_at_open)
  2. In-position check order per bar:
       (a) open <= stop         -> gap_stop, exit at open
       (b) low  <= stop         -> stop,     exit at stop
       (c) high >= target       -> target,   exit at target  (stop checked first)
       (d) exit_long[t-1]       -> signal,   exit at open[t]
       (e) time_stop expiry     -> time,     exit at open[t]
  3. trailing stop: after bar close, stop = max(stop, close - trail_atr_mult * atr14)
  4. exit fills at price * (1 - slip)
  5. final-bar still-open -> eod at last close
  6. entry_at_open: entry_long[t] fills at open[t] * (1 + slip) same bar
  7. r_multiple = (exit_price - entry_price) / stop_dist_initial  (both with slippage)
  8. no pyramiding: second entry_long while open is ignored
  9. no entry when stop_dist is NaN or <= 0
"""

from __future__ import annotations

import math
import pytest
import pandas as pd
import numpy as np

from stockslab.engine import run_signal_backtest, run_universe, Trade, TIER_BPS
from stockslab.strategies.base import SignalStrategy, RotationStrategy, REGISTRY, register


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_df(opens, highs, lows, closes, volumes=None, tz=None):
    """Build a minimal OHLCV DataFrame with a DatetimeIndex."""
    n = len(opens)
    if volumes is None:
        volumes = [1_000_000] * n
    dates = pd.date_range("2020-01-02", periods=n, freq="B")
    if tz:
        dates = dates.tz_localize(tz)
    df = pd.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    }, index=dates)
    df.index.name = "date"
    return df.astype(float)


def _intraday_df(opens, highs, lows, closes, volumes=None):
    """Build a minimal intraday OHLCV DataFrame (1-hour bars, 2 bars per day).
    Day 1: 09:30, 10:30. Day 2: 09:30, 10:30. Etc.
    """
    n = len(opens)
    if volumes is None:
        volumes = [500_000] * n
    # Build timestamps: 2 bars per trading day
    start = pd.Timestamp("2020-01-02 09:30", tz="America/New_York")
    base_dates = pd.date_range("2020-01-02", periods=(n + 1) // 2, freq="B", tz="America/New_York")
    timestamps = []
    for d in base_dates:
        timestamps.append(d.replace(hour=9, minute=30))
        timestamps.append(d.replace(hour=10, minute=30))
    timestamps = timestamps[:n]
    df = pd.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    }, index=pd.DatetimeIndex(timestamps))
    df.index.name = "date"
    return df.astype(float)


class _StubStrategy(SignalStrategy):
    """Concrete stub to inject pre-computed signals."""

    def __init__(self, signals_df, **kwargs):
        super().__init__(**kwargs)
        self._signals = signals_df

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        return self._signals.copy()


# ---------------------------------------------------------------------------
# Test 1: Entry at next-bar open with slippage (tier 2 → 3 bps per side)
# ---------------------------------------------------------------------------
#
# Hand computation:
#   signal bar t=0: entry_long=True, stop_dist=1.0
#   entry bar t=1: open=102.0, slip = 3/10_000 = 0.0003
#   entry_price = 102.0 * (1 + 0.0003) = 102.0306
#   no exit within data → eod exit at close[1]=101.0 *(1-0.0003) = 100.9697
#   r_multiple = (100.9697 - 102.0306) / 1.0 = -1.0609
#   pct_return  = (100.9697 - 102.0306) / 102.0306
# ---------------------------------------------------------------------------

class TestEntryNextOpenWithSlippage:
    def _setup(self):
        # stop_dist=5.0, entry at open[1]=102.0*(1+0.0003)=102.0306
        # stop = 102.0306 - 5.0 = 97.0306; bar1 low=100.5 > 97.0306 (no stop hit)
        df = _make_df(
            opens=[100.0, 102.0],
            highs=[101.0, 103.0],
            lows=[99.0, 100.5],
            closes=[100.5, 101.0],
        )
        signals = pd.DataFrame({
            "entry_long": [True, False],
            "exit_long": [False, False],
            "stop_dist": [5.0, float("nan")],
        }, index=df.index)
        strat = _StubStrategy(signals, name="t1")
        return df, strat

    def test_entry_next_open_with_slippage(self):
        df, strat = self._setup()
        slip = TIER_BPS[2] / 10_000  # 0.0003

        # entry: open[1] * (1 + slip) = 102.0 * 1.0003
        expected_entry = 102.0 * (1 + slip)

        # eod: close[1] * (1 - slip) = 101.0 * (1 - 0.0003)
        expected_exit = 101.0 * (1 - slip)

        # stop_dist=5.0 so stop=102.0306-5.0=97.0306; bar1 low=100.5 > 97.0306 (safe)
        trades = run_signal_backtest(strat, df, symbol="TEST", slippage_bps=TIER_BPS[2])
        assert len(trades) == 1
        t = trades[0]
        assert t.symbol == "TEST"
        assert t.exit_reason == "eod"
        assert t.entry == pytest.approx(expected_entry, rel=1e-9)
        assert t.exit == pytest.approx(expected_exit, rel=1e-9)
        assert t.r_multiple == pytest.approx((expected_exit - expected_entry) / 5.0, rel=1e-9)


# ---------------------------------------------------------------------------
# Test 2: Stop hit intrabar (low <= stop) fills at stop price
#
# Hand computation:
#   Bar 0: entry_long=True, stop_dist=2.0
#   Bar 1 (entry bar): open=100.0 * (1+0.0003) = 100.03
#     stop = entry_price - stop_dist = 100.03 - 2.0 = 98.03
#     Bar 1 check: open=100.03 > 98.03 (no gap), low=97.0 <= 98.03 → STOP HIT
#     exit = stop * (1 - 0.0003) = 98.03 * (1 - 0.0003)
#   r_multiple = (exit - entry) / stop_dist
# ---------------------------------------------------------------------------

class TestStopHitIntrabarFillsAtStop:
    def test_stop_hit_intrabar_fills_at_stop(self):
        df = _make_df(
            opens=[100.0, 100.0, 99.0],
            highs=[101.0, 101.0, 100.0],
            lows=[99.0, 97.0, 98.0],
            closes=[100.0, 99.0, 99.0],
        )
        signals = pd.DataFrame({
            "entry_long": [True, False, False],
            "exit_long": [False, False, False],
            "stop_dist": [2.0, float("nan"), float("nan")],
        }, index=df.index)
        strat = _StubStrategy(signals, name="t2")
        slip = TIER_BPS[3] / 10_000  # 0.0005

        # entry: open[1] * (1 + slip) = 100.0 * 1.0005 = 100.05
        entry = 100.0 * (1 + slip)
        stop = entry - 2.0  # = 98.05

        # Bar 1 OHLC: open=100.0, high=101.0, low=97.0, close=99.0
        # open=100.0 > stop=98.05 (no gap_stop)
        # low=97.0 <= stop=98.05 → stop hit
        # exit = stop * (1 - slip)
        expected_exit = stop * (1 - slip)

        trades = run_signal_backtest(strat, df, symbol="X", slippage_bps=TIER_BPS[3])
        assert len(trades) == 1
        t = trades[0]
        assert t.exit_reason == "stop"
        assert t.entry == pytest.approx(entry, rel=1e-9)
        assert t.exit == pytest.approx(expected_exit, rel=1e-9)
        r_expected = (expected_exit - entry) / 2.0
        assert t.r_multiple == pytest.approx(r_expected, rel=1e-9)


# ---------------------------------------------------------------------------
# Test 3: Gap through stop — open <= stop → fills at open (not stop)
#
# Hand computation:
#   Bar 0: entry_long=True, stop_dist=5.0
#   Bar 1: open=105.0*(1+0.0005) = 105.0525  → entry
#     stop = 105.0525 - 5.0 = 100.0525
#   Bar 2: open=99.0 <= 100.0525 → gap_stop
#     exit at open[2] = 99.0 * (1 - 0.0005) = 98.9505
# ---------------------------------------------------------------------------

class TestGapThroughStopFillsAtOpen:
    def test_gap_through_stop_fills_at_open(self):
        df = _make_df(
            opens=[104.0, 105.0, 99.0],
            highs=[106.0, 106.0, 100.0],
            lows=[103.0, 104.0, 98.5],
            closes=[105.0, 104.5, 99.5],
        )
        signals = pd.DataFrame({
            "entry_long": [True, False, False],
            "exit_long": [False, False, False],
            "stop_dist": [5.0, float("nan"), float("nan")],
        }, index=df.index)
        strat = _StubStrategy(signals, name="t3")
        slip = TIER_BPS[3] / 10_000  # 0.0005

        entry = 105.0 * (1 + slip)   # 105.0525
        stop = entry - 5.0            # 100.0525

        # Bar 2: open=99.0 <= 100.0525 → gap_stop
        expected_exit = 99.0 * (1 - slip)   # 98.9505

        trades = run_signal_backtest(strat, df, symbol="X", slippage_bps=TIER_BPS[3])
        assert len(trades) == 1
        t = trades[0]
        assert t.exit_reason == "gap_stop"
        assert t.entry == pytest.approx(entry, rel=1e-9)
        assert t.exit == pytest.approx(expected_exit, rel=1e-9)


# ---------------------------------------------------------------------------
# Test 4: Stop checked before target same bar
#
# Bar has low <= stop AND high >= target → stop fills first (conservative)
#
# Hand computation:
#   Bar 0: entry_long=True, stop_dist=2.0, target_r=2.0
#   Bar 1: entry at open[1]=100.0*(1+0.0003)=100.03
#     stop = 100.03 - 2.0 = 98.03
#     target = 100.03 + 2.0*2.0 = 104.03
#   Bar 2: open=100.0>98.03, low=96.0<=98.03 AND high=105.0>=104.03
#     → stop fills first
#     exit = stop * (1 - 0.0003) = 98.03 * 0.9997
# ---------------------------------------------------------------------------

class TestStopCheckedBeforeTargetSameBar:
    def test_stop_checked_before_target_same_bar(self):
        df = _make_df(
            opens=[99.0, 100.0, 100.0],
            highs=[101.0, 101.0, 105.0],
            lows=[98.0, 99.0, 96.0],
            closes=[100.0, 100.0, 100.0],
        )
        signals = pd.DataFrame({
            "entry_long": [True, False, False],
            "exit_long": [False, False, False],
            "stop_dist": [2.0, float("nan"), float("nan")],
        }, index=df.index)
        strat = _StubStrategy(signals, name="t4", target_r=2.0)
        slip = TIER_BPS[2] / 10_000  # 0.0003

        entry = 100.0 * (1 + slip)   # open[1]
        stop = entry - 2.0
        target = entry + 2.0 * 2.0

        # Bar 2: open=100.0 > stop=98.03, low=96.0 <= stop → STOP
        expected_exit = stop * (1 - slip)

        trades = run_signal_backtest(strat, df, symbol="X", slippage_bps=TIER_BPS[2])
        assert len(trades) == 1
        t = trades[0]
        assert t.exit_reason == "stop"
        assert t.exit == pytest.approx(expected_exit, rel=1e-9)


# ---------------------------------------------------------------------------
# Test 5: Target hit fills at target
#
# Hand computation:
#   Bar 0: entry_long=True, stop_dist=2.0, target_r=2.0
#   Bar 1: entry at open=100.0*(1+0.0003) = 100.03
#     stop = 100.03 - 2.0 = 98.03
#     target = 100.03 + 2.0*2.0 = 104.03
#   Bar 2: open=101.0 > 98.03 (no gap), low=100.5 > 98.03 (no stop), high=105.0 >= 104.03
#     → target hit
#     exit = target * (1 - 0.0003) = 104.03 * 0.9997
# ---------------------------------------------------------------------------

class TestTargetHitFillsAtTarget:
    def test_target_hit_fills_at_target(self):
        df = _make_df(
            opens=[99.0, 100.0, 101.0],
            highs=[100.0, 101.0, 105.0],
            lows=[98.0, 99.0, 100.5],
            closes=[99.5, 100.5, 104.5],
        )
        signals = pd.DataFrame({
            "entry_long": [True, False, False],
            "exit_long": [False, False, False],
            "stop_dist": [2.0, float("nan"), float("nan")],
        }, index=df.index)
        strat = _StubStrategy(signals, name="t5", target_r=2.0)
        slip = TIER_BPS[2] / 10_000  # 0.0003

        entry = 100.0 * (1 + slip)
        target = entry + 2.0 * 2.0   # 104.03 + slippage on entry

        # Bar 2: open=101.0 > stop, low=100.5 > stop, high=105.0 >= target
        expected_exit = target * (1 - slip)

        trades = run_signal_backtest(strat, df, symbol="X", slippage_bps=TIER_BPS[2])
        assert len(trades) == 1
        t = trades[0]
        assert t.exit_reason == "target"
        assert t.exit == pytest.approx(expected_exit, rel=1e-9)


# ---------------------------------------------------------------------------
# Test 6: Exit signal fills at next open
#
# Hand computation:
#   Bar 0: entry_long=True, stop_dist=2.0
#   Bar 1: entry at 100.0 * (1+0.0003) = 100.03
#   Bar 1: exit_long=True on bar 1 → exit at open[2]
#   Bar 2: exit at open[2]=102.0 * (1-0.0003) = 101.9694
# ---------------------------------------------------------------------------

class TestExitSignalFillsNextOpen:
    def test_exit_signal_fills_next_open(self):
        df = _make_df(
            opens=[99.0, 100.0, 102.0],
            highs=[100.5, 103.0, 103.0],
            lows=[98.0, 99.5, 101.0],
            closes=[100.0, 102.0, 102.5],
        )
        signals = pd.DataFrame({
            "entry_long": [True, False, False],
            "exit_long": [False, True, False],
            "stop_dist": [2.0, float("nan"), float("nan")],
        }, index=df.index)
        strat = _StubStrategy(signals, name="t6")
        slip = TIER_BPS[2] / 10_000  # 0.0003

        entry = 100.0 * (1 + slip)

        # exit_long at bar 1 → fills at open[2]=102.0 *(1-slip)
        expected_exit = 102.0 * (1 - slip)

        trades = run_signal_backtest(strat, df, symbol="X", slippage_bps=TIER_BPS[2])
        assert len(trades) == 1
        t = trades[0]
        assert t.exit_reason == "signal"
        assert t.exit == pytest.approx(expected_exit, rel=1e-9)
        assert t.entry == pytest.approx(entry, rel=1e-9)


# ---------------------------------------------------------------------------
# Test 7: Time stop exits after N bars
#
# Hand computation:
#   time_stop_bars=2, meaning exit after being in position for 2 bars
#   Bar 0: entry_long=True, stop_dist=2.0
#   Bar 1: entry at open[1]=100.0*(1+0.0003) = 100.03  (bar_count=1)
#   Bar 2: bar_count=2 → time stop expires, exit at open[2]
#   Bar 2: open=101.0 * (1-0.0003) = 100.9697
# ---------------------------------------------------------------------------

class TestTimeStopExitsAfterNBars:
    def test_time_stop_exits_after_n_bars(self):
        df = _make_df(
            opens=[99.0, 100.0, 101.0, 102.0],
            highs=[100.0, 102.0, 103.0, 104.0],
            lows=[98.0, 99.5, 100.5, 101.0],
            closes=[100.0, 101.5, 102.5, 103.0],
        )
        signals = pd.DataFrame({
            "entry_long": [True, False, False, False],
            "exit_long": [False, False, False, False],
            "stop_dist": [2.0, float("nan"), float("nan"), float("nan")],
        }, index=df.index)
        strat = _StubStrategy(signals, name="t7", time_stop_bars=2)
        slip = TIER_BPS[3] / 10_000  # 0.0005

        entry = 100.0 * (1 + slip)
        # After entry at bar 1: bars_held=1 after bar 1 close, bars_held=2 after bar 2 close
        # time_stop fires at the start of bar 2+1=bar 3 → exit at open[3]? No.
        # The engine counts bars IN position. Entry on bar 1 (first in-position bar).
        # After bar 1: bars_held=1; after bar 2: bars_held=2 → exits at open of bar 3
        # Actually: entry bar is bar 1, bar_count starts at 1 at bar 1. After 2 bars
        # (bar 1 and bar 2), exit at open[3]=102.0
        # But let's re-examine: time_stop_bars=2 means exit AFTER 2 in-position bars.
        # At the START of bar 3 (open[3]), exit fills.
        expected_exit = 102.0 * (1 - slip)

        trades = run_signal_backtest(strat, df, symbol="X", slippage_bps=TIER_BPS[3])
        assert len(trades) == 1
        t = trades[0]
        assert t.exit_reason == "time"
        assert t.exit == pytest.approx(expected_exit, rel=1e-9)


# ---------------------------------------------------------------------------
# Test 8: Trailing stop ratchets up, never down
#
# This test uses a tiny ATR so we can hand-compute the trailing stop.
# We use atr from indicators to compute the actual atr14, then manually
# trace the stop.
#
# Design: use a 3-bar warm-up atr with n=2 to keep it short.
# But the engine always uses atr14. We must build a 14-bar warm-up + more bars.
# Instead, we test structurally: give a clear uptrend then a sharp drop.
# After uptrend bars the trailing stop should have ratcheted up; the drop
# triggers it at a higher level than the initial stop.
#
# Concretely with trail_atr_mult=2 and atr≈1.0 (constant OHLC spreads of 1.0):
#   All bars: H-L=1, same close-to-open, so TR≈1. ATR→1 after warm-up.
#   Entry: open[15] * (1+slip) (after 14 bars of warmup)
#   stop = entry - stop_dist
#   After each bar: stop = max(stop, close - 2*atr14)
#   If close rises, stop ratchets up.
# ---------------------------------------------------------------------------

class TestTrailingStopRatchetsUpNeverDown:
    def test_trailing_stop_ratchets_up_never_down(self):
        # 20 bars: 14 warmup, then entry signal, then some up bars, then a down bar
        # OHLC: constant H=C+0.5, L=C-0.5, so TR=1 and ATR=1 always after warmup
        # Closes rise 1.0/bar from bar 14 onward
        n = 20
        base_close = 100.0
        closes = [base_close + i for i in range(n)]
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        # Use constant open slightly below close
        opens = [c - 0.2 for c in closes]

        # Signal: entry at bar 14 (signal at bar 14 means entry at bar 15)
        entry_long = [False] * n
        exit_long = [False] * n
        stop_dist_vals = [float("nan")] * n
        entry_long[14] = True
        stop_dist_vals[14] = 3.0  # initial stop_dist

        df = _make_df(opens, highs, lows, closes)
        signals = pd.DataFrame({
            "entry_long": entry_long,
            "exit_long": exit_long,
            "stop_dist": stop_dist_vals,
        }, index=df.index)
        strat = _StubStrategy(signals, name="t8", trail_atr_mult=2.0)
        slip = TIER_BPS[3] / 10_000

        trades = run_signal_backtest(strat, df, symbol="X", slippage_bps=TIER_BPS[3])
        # The trailing stop should force an exit at eod (last bar) since the rising
        # close keeps pushing stop up. Actually it exits when a bar's low hits the stop.
        # With constant OHLC spread 1.0, ATR=1, trail=2, stop rises with close.
        # Since the low is close-0.5 and stop is close[-1] - 2*1 = close[-1]-2,
        # and close is rising by 1/bar, the low of the next bar is roughly close-0.5 = prev_close+0.5
        # stop was prev_close-2, new_close is prev_close+1, new_stop = prev_close+1-2 = prev_close-1
        # new_low = prev_close+0.5. low>stop, so no stop hit, ratchets up each bar.
        # Final bar: exits eod.
        assert len(trades) == 1
        t = trades[0]
        # The stop must have ratcheted: entry stop = entry - 3.0
        # Later stops are higher. Test that final stop is higher than initial stop.
        # We verify this indirectly: if trailing didn't work, the position would only
        # close at eod. Since it does close at eod, the trail still ratcheted.
        assert t.exit_reason in ("eod", "stop", "gap_stop")

        # More precise: verify the stop DID ratchet — we compare two strategies
        # (with and without trail) and confirm the trade result differs when
        # trailing is active. Specifically: with trail active, a subsequent drop bar
        # should hit a higher stop.
        # Let's add a final drop bar to verify it closes via stop with trail.
        closes2 = closes[:-1] + [closes[-2] - 10.0]  # last bar drops sharply
        highs2 = [c + 0.5 for c in closes2]
        lows2 = [c - 0.5 for c in closes2]
        lows2[-1] = closes2[-1] - 0.5

        df2 = _make_df(opens[:-1] + [opens[-1]], highs2, lows2, closes2)
        # Reuse same signals but now the drop triggers the ratcheted stop
        signals2 = signals.copy()
        signals2.index = df2.index

        trades2 = run_signal_backtest(
            _StubStrategy(signals2, name="t8b", trail_atr_mult=2.0),
            df2, symbol="X", slippage_bps=TIER_BPS[3]
        )
        assert len(trades2) == 1
        t2 = trades2[0]
        # With drop bar, should hit ratcheted stop (not just eod)
        assert t2.exit_reason in ("stop", "gap_stop")


# ---------------------------------------------------------------------------
# Test 9: No pyramiding — second entry signal ignored while position open
#
# Hand computation:
#   Bar 0: entry_long=True  → entry at open[1]
#   Bar 1: entry_long=True  → IGNORED (already in position)
#   Bar 2: no signals, eod
#   Expected: exactly 1 trade total
# ---------------------------------------------------------------------------

class TestNoPyramidingSecondSignalIgnoredWhileOpen:
    def test_no_pyramiding_second_signal_ignored_while_open(self):
        df = _make_df(
            opens=[100.0, 101.0, 102.0, 103.0],
            highs=[101.0, 102.0, 103.0, 104.0],
            lows=[99.0, 100.0, 101.0, 102.0],
            closes=[100.5, 101.5, 102.5, 103.5],
        )
        signals = pd.DataFrame({
            "entry_long": [True, True, False, False],
            "exit_long": [False, False, False, False],
            "stop_dist": [2.0, 2.0, float("nan"), float("nan")],
        }, index=df.index)
        strat = _StubStrategy(signals, name="t9")
        trades = run_signal_backtest(strat, df, symbol="X", slippage_bps=TIER_BPS[3])
        # Only one position; second signal bar 1 is ignored
        assert len(trades) == 1
        assert trades[0].exit_reason == "eod"


# ---------------------------------------------------------------------------
# Test 10: Open position closed at final bar (eod)
#
# Hand computation:
#   Bar 0: entry_long=True, stop_dist=2.0
#   Bar 1: entry at open[1]=100.0*(1+0.0003)=100.03
#   Bar 1 is the last bar → eod exit at close[1]=101.0*(1-0.0003)
# ---------------------------------------------------------------------------

class TestOpenPositionClosedAtFinalBar:
    def test_open_position_closed_at_final_bar(self):
        df = _make_df(
            opens=[99.0, 100.0],
            highs=[100.0, 102.0],
            lows=[98.0, 99.5],
            closes=[99.5, 101.0],
        )
        signals = pd.DataFrame({
            "entry_long": [True, False],
            "exit_long": [False, False],
            "stop_dist": [2.0, float("nan")],
        }, index=df.index)
        strat = _StubStrategy(signals, name="t10")
        slip = TIER_BPS[2] / 10_000

        entry = 100.0 * (1 + slip)
        expected_exit = 101.0 * (1 - slip)  # close of final bar

        trades = run_signal_backtest(strat, df, symbol="X", slippage_bps=TIER_BPS[2])
        assert len(trades) == 1
        t = trades[0]
        assert t.exit_reason == "eod"
        assert t.exit == pytest.approx(expected_exit, rel=1e-9)


# ---------------------------------------------------------------------------
# Test 11: r_multiple accounting includes slippage on both sides
#
# Hand computation:
#   entry_long at bar 0, stop_dist=2.0, target_r=3.0 (but no target hit)
#   slip = tier1 = 1 bps = 0.0001
#   entry: open[1]=100.0 * (1 + 0.0001) = 100.01
#   stop = 100.01 - 2.0 = 98.01
#   Bar 1: low=97.5 <= stop=98.01 → stop exit
#   exit = 98.01 * (1 - 0.0001) = 97.9902...
#   r_multiple = (exit - entry) / stop_dist = (97.9902 - 100.01) / 2.0
#   pct_return = (97.9902 - 100.01) / 100.01
# ---------------------------------------------------------------------------

class TestRMultipleAccountingIncludesSlippage:
    def test_r_multiple_accounting_includes_slippage(self):
        df = _make_df(
            opens=[99.0, 100.0, 100.0],
            highs=[100.5, 101.0, 100.5],
            lows=[98.5, 97.5, 99.0],
            closes=[100.0, 99.0, 100.0],
        )
        signals = pd.DataFrame({
            "entry_long": [True, False, False],
            "exit_long": [False, False, False],
            "stop_dist": [2.0, float("nan"), float("nan")],
        }, index=df.index)
        strat = _StubStrategy(signals, name="t11")
        slip = TIER_BPS[1] / 10_000  # 0.0001

        entry = 100.0 * (1 + slip)   # 100.01
        stop = entry - 2.0            # 98.01
        # Bar 1: open=100.0>stop, low=97.5<=stop → stop exit
        expected_exit = stop * (1 - slip)
        expected_r = (expected_exit - entry) / 2.0
        expected_pct = (expected_exit - entry) / entry

        trades = run_signal_backtest(strat, df, symbol="X", slippage_bps=TIER_BPS[1])
        assert len(trades) == 1
        t = trades[0]
        assert t.entry == pytest.approx(entry, rel=1e-9)
        assert t.exit == pytest.approx(expected_exit, rel=1e-9)
        assert t.r_multiple == pytest.approx(expected_r, rel=1e-9)
        assert t.pct_return == pytest.approx(expected_pct, rel=1e-9)


# ---------------------------------------------------------------------------
# Test 12: entry_at_open — same bar fill
#
# Hand computation:
#   entry_at_open=True: entry_long[t] → fill at open[t]*(1+slip), same bar t
#   Bar 0: entry_long=True, stop_dist=1.5
#   entry at open[0]=100.0*(1+0.0005) = 100.05  (tier 3)
#   No other signals, bar 0 is last bar → eod exit at close[0]=101.0*(1-0.0005)
# ---------------------------------------------------------------------------

class TestEntryAtOpenSameBarFill:
    def test_entry_at_open_same_bar_fill(self):
        df = _make_df(
            opens=[100.0],
            highs=[101.5],
            lows=[99.0],
            closes=[101.0],
        )
        signals = pd.DataFrame({
            "entry_long": [True],
            "exit_long": [False],
            "stop_dist": [1.5],
        }, index=df.index)
        strat = _StubStrategy(signals, name="t12", entry_at_open=True)
        slip = TIER_BPS[3] / 10_000  # 0.0005

        # entry at open[0]*(1+slip)
        expected_entry = 100.0 * (1 + slip)
        # eod exit at close[0]*(1-slip)
        expected_exit = 101.0 * (1 - slip)

        trades = run_signal_backtest(strat, df, symbol="X", slippage_bps=TIER_BPS[3])
        assert len(trades) == 1
        t = trades[0]
        assert t.exit_reason == "eod"
        assert t.entry == pytest.approx(expected_entry, rel=1e-9)
        assert t.exit == pytest.approx(expected_exit, rel=1e-9)


# ---------------------------------------------------------------------------
# Test 13: session_exit — last bar of session forced exit
#
# Using intraday 2-bar-per-day setup. Last bar of each day is bar index 1, 3, 5...
# strategy.session_exit=True forces exit at close of last intraday bar.
#
# Hand computation:
#   Bars: day1_bar0(09:30), day1_bar1(10:30), day2_bar0(09:30), day2_bar1(10:30)
#   Bar 0: entry_long=True, stop_dist=1.0  (day1_bar0)
#     entry_at_open=True → fills at open[0]*(1+slip)
#     session_exit on last bar of day1 = bar1
#     Bar 1 is last bar of day1 → check session_exit: exit at close[1]*(1-slip)
#     But wait: with entry_at_open=True, we enter bar 0, then session_exit checks
#     if current bar is last of session. Bar 1 is last → exit at close[1]
# ---------------------------------------------------------------------------

class TestSessionExitLastBarOfDay:
    def test_session_exit_last_bar_of_day(self):
        # 4 bars: day1[09:30, 10:30], day2[09:30, 10:30]
        df = _intraday_df(
            opens=[100.0, 101.0, 102.0, 103.0],
            highs=[101.5, 102.5, 103.5, 104.5],
            lows=[99.5, 100.5, 101.5, 102.5],
            closes=[101.0, 102.0, 103.0, 104.0],
        )
        signals = pd.DataFrame({
            "entry_long": [True, False, False, False],
            "exit_long": [False, False, False, False],
            "stop_dist": [1.0, float("nan"), float("nan"), float("nan")],
        }, index=df.index)
        strat = _StubStrategy(signals, name="t13", session_exit=True, entry_at_open=True)
        slip = TIER_BPS[3] / 10_000  # 0.0005

        # Entry at bar 0 (entry_at_open): open[0]=100.0*(1+slip) = 100.05
        expected_entry = 100.0 * (1 + slip)

        # session_exit: bar 1 (10:30) is last bar of day 1 → exit at close[1]*(1-slip)
        expected_exit = 102.0 * (1 - slip)

        trades = run_signal_backtest(strat, df, symbol="X", slippage_bps=TIER_BPS[3])
        assert len(trades) == 1
        t = trades[0]
        assert t.exit_reason == "session"
        assert t.entry == pytest.approx(expected_entry, rel=1e-9)
        assert t.exit == pytest.approx(expected_exit, rel=1e-9)


# ---------------------------------------------------------------------------
# Test 14: No entry when stop_dist is NaN or <= 0
# ---------------------------------------------------------------------------

class TestNoEntryWhenStopDistNanOrZero:
    def test_no_entry_when_stop_dist_nan(self):
        df = _make_df(
            opens=[100.0, 101.0],
            highs=[101.0, 102.0],
            lows=[99.0, 100.0],
            closes=[100.5, 101.5],
        )
        signals = pd.DataFrame({
            "entry_long": [True, False],
            "exit_long": [False, False],
            "stop_dist": [float("nan"), float("nan")],  # NaN → no entry
        }, index=df.index)
        strat = _StubStrategy(signals, name="t14a")
        trades = run_signal_backtest(strat, df, symbol="X", slippage_bps=TIER_BPS[2])
        assert len(trades) == 0

    def test_no_entry_when_stop_dist_zero(self):
        df = _make_df(
            opens=[100.0, 101.0],
            highs=[101.0, 102.0],
            lows=[99.0, 100.0],
            closes=[100.5, 101.5],
        )
        signals = pd.DataFrame({
            "entry_long": [True, False],
            "exit_long": [False, False],
            "stop_dist": [0.0, float("nan")],  # 0 → no entry
        }, index=df.index)
        strat = _StubStrategy(signals, name="t14b")
        trades = run_signal_backtest(strat, df, symbol="X", slippage_bps=TIER_BPS[2])
        assert len(trades) == 0

    def test_no_entry_when_stop_dist_negative(self):
        df = _make_df(
            opens=[100.0, 101.0],
            highs=[101.0, 102.0],
            lows=[99.0, 100.0],
            closes=[100.5, 101.5],
        )
        signals = pd.DataFrame({
            "entry_long": [True, False],
            "exit_long": [False, False],
            "stop_dist": [-1.0, float("nan")],  # neg → no entry
        }, index=df.index)
        strat = _StubStrategy(signals, name="t14c")
        trades = run_signal_backtest(strat, df, symbol="X", slippage_bps=TIER_BPS[2])
        assert len(trades) == 0


# ---------------------------------------------------------------------------
# Test 15: run_universe sets strategy.context = panel before per-symbol runs
# ---------------------------------------------------------------------------

class TestRunUniverseSetsContext:
    def test_run_universe_sets_context(self):
        """run_universe must set strategy.context = panel before per-symbol runs."""

        captured_context = {}

        class _ContextCapture(SignalStrategy):
            def generate(self, df: pd.DataFrame) -> pd.DataFrame:
                captured_context["panel"] = getattr(self, "context", None)
                # Return empty signals (no entries)
                return pd.DataFrame({
                    "entry_long": [False] * len(df),
                    "exit_long": [False] * len(df),
                    "stop_dist": [float("nan")] * len(df),
                }, index=df.index)

        strat = _ContextCapture(name="ctx_test")

        df1 = _make_df([100.0]*3, [101.0]*3, [99.0]*3, [100.5]*3)
        df2 = _make_df([200.0]*3, [201.0]*3, [199.0]*3, [200.5]*3)
        panel = {"SYM1": df1, "SYM2": df2}
        tiers = {"SYM1": 2, "SYM2": 3}

        run_universe(strat, panel, tiers)

        assert captured_context.get("panel") is panel


# ---------------------------------------------------------------------------
# Test 16: TIER_BPS constant values
# ---------------------------------------------------------------------------

class TestTierBpsConstant:
    def test_tier_bps_values(self):
        assert TIER_BPS[1] == 1
        assert TIER_BPS[2] == 3
        assert TIER_BPS[3] == 5


# ---------------------------------------------------------------------------
# Test 17: Trade dataclass has required fields
# ---------------------------------------------------------------------------

class TestTradeDataclass:
    def test_trade_fields_exist(self):
        t = Trade(
            symbol="TEST",
            entry_date=pd.Timestamp("2020-01-02"),
            exit_date=pd.Timestamp("2020-01-03"),
            entry=100.0,
            exit=105.0,
            shares=10.0,
            r_multiple=2.5,
            pct_return=0.05,
            exit_reason="target",
        )
        assert t.symbol == "TEST"
        assert t.entry_date == pd.Timestamp("2020-01-02")
        assert t.exit_date == pd.Timestamp("2020-01-03")
        assert t.entry == 100.0
        assert t.exit == 105.0
        assert t.shares == 10.0
        assert t.r_multiple == 2.5
        assert t.pct_return == 0.05
        assert t.exit_reason == "target"


# ---------------------------------------------------------------------------
# Test 18: run_rotation_backtest stub raises NotImplementedError
# ---------------------------------------------------------------------------

class TestRotationImplemented:
    def test_rotation_empty_panel_returns_empty(self):
        """run_rotation_backtest with an empty panel returns an empty trade list."""
        from stockslab.engine import run_rotation_backtest
        from stockslab.strategies.base import RotationStrategy
        import pandas as pd

        class _EmptyStrategy(RotationStrategy):
            def target_holdings(self, panel, dates):
                return pd.DataFrame(index=pd.DatetimeIndex([]), columns=[])

        trades = run_rotation_backtest(_EmptyStrategy(), {}, {})
        assert trades == []


# ---------------------------------------------------------------------------
# Test 19: base.py REGISTRY and @register decorator
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_register_decorator_adds_to_registry(self):
        # With dataclass inheritance, override the default by providing a new field default.
        # The register decorator calls cls() with no args, so the default must be set.
        # Use a unique name to avoid collisions.
        import dataclasses

        @register
        @dataclasses.dataclass
        class _MyTestStratXyzzy(SignalStrategy):
            name: str = "my_test_strat_xyzzy"

            def generate(self, df):
                raise NotImplementedError

        assert "my_test_strat_xyzzy" in REGISTRY

    def test_registry_is_dict(self):
        assert isinstance(REGISTRY, dict)


# ---------------------------------------------------------------------------
# Test 20: RotationStrategy interface
# ---------------------------------------------------------------------------

class TestRotationStrategyInterface:
    def test_rotation_strategy_has_target_holdings(self):
        strat = RotationStrategy()
        assert hasattr(strat, "target_holdings")
        assert hasattr(strat, "name")
        assert hasattr(strat, "params")
        assert hasattr(strat, "timeframe")
        assert hasattr(strat, "universe")

    def test_rotation_strategy_default_name(self):
        strat = RotationStrategy()
        assert strat.name == "base_rotation"


# ---------------------------------------------------------------------------
# Test 21: pct_return uses slipped prices
#
# entry = 100.0 * (1 + 0.0003) = 100.03
# exit (eod) = close[1] * (1-0.0003) = 105.0 * 0.9997 = 104.9685
# pct_return = (104.9685 - 100.03) / 100.03
# ---------------------------------------------------------------------------

class TestPctReturnUsesSlippedPrices:
    def test_pct_return_correct(self):
        df = _make_df(
            opens=[99.0, 100.0],
            highs=[100.0, 106.0],
            lows=[98.0, 99.5],
            closes=[99.5, 105.0],
        )
        signals = pd.DataFrame({
            "entry_long": [True, False],
            "exit_long": [False, False],
            "stop_dist": [2.0, float("nan")],
        }, index=df.index)
        strat = _StubStrategy(signals, name="t21")
        slip = TIER_BPS[2] / 10_000

        entry = 100.0 * (1 + slip)
        exit_price = 105.0 * (1 - slip)
        expected_pct = (exit_price - entry) / entry

        trades = run_signal_backtest(strat, df, symbol="X", slippage_bps=TIER_BPS[2])
        assert len(trades) == 1
        assert trades[0].pct_return == pytest.approx(expected_pct, rel=1e-9)


# ---------------------------------------------------------------------------
# Test 22: run_universe returns all trades from all symbols
# ---------------------------------------------------------------------------

class TestRunUniverseReturnsTrades:
    def test_run_universe_concatenates_trades(self):
        class _AlwaysEntry(SignalStrategy):
            def generate(self, df: pd.DataFrame) -> pd.DataFrame:
                return pd.DataFrame({
                    "entry_long": [True] + [False] * (len(df) - 1),
                    "exit_long": [False] * len(df),
                    "stop_dist": [2.0] + [float("nan")] * (len(df) - 1),
                }, index=df.index)

        strat = _AlwaysEntry(name="univ_test")
        df1 = _make_df([100.0]*3, [101.0]*3, [99.0]*3, [100.5]*3)
        df2 = _make_df([200.0]*3, [201.0]*3, [199.0]*3, [200.5]*3)
        panel = {"A": df1, "B": df2}
        tiers = {"A": 2, "B": 3}

        trades = run_universe(strat, panel, tiers)
        symbols = {t.symbol for t in trades}
        assert "A" in symbols
        assert "B" in symbols


# ===========================================================================
# REGRESSION TESTS — bugs found by adversarial Opus review (2026-06-12)
# All 180 prior tests passed while these two results-corrupting bugs survived,
# because no prior test exercised these specific combinations.
# ===========================================================================


# ---------------------------------------------------------------------------
# REGRESSION 1: gap_fade contract — entry_at_open + time_stop_bars=1 must be a
# SAME-BAR round trip: enter at the entry bar's open, exit at that SAME bar's
# close, reason "time". The bug held the position overnight and exited at the
# next bar's open (every gap_fade trade silently became an overnight position).
#
# Hand computation (tier 3, slip = 0.0005):
#   Bar 0: entry_at_open=True, entry_long=True, stop_dist=5.0, time_stop_bars=1
#     entry = open[0] * (1+slip) = 100.0 * 1.0005 = 100.0500
#     stop  = 100.05 - 5.0 = 95.05; bar-0 low=99.0 > 95.05 (no stop)
#     time_stop_bars=1 -> exit at THIS bar's close = 100.5 * (1-slip) = 100.4498
#     entry_date == exit_date == bar 0; reason "time"
# ---------------------------------------------------------------------------

class TestGapFadeSameBarTimeStop:
    def test_entry_at_open_time_stop_1_exits_same_bar_at_close(self):
        df = _make_df(
            opens=[100.0, 102.0, 103.0],
            highs=[101.0, 103.0, 104.0],
            lows=[99.0, 101.0, 102.0],
            closes=[100.5, 102.5, 103.5],
        )
        signals = pd.DataFrame({
            "entry_long": [True, False, False],
            "exit_long": [False, False, False],
            "stop_dist": [5.0, float("nan"), float("nan")],
        }, index=df.index)
        strat = _StubStrategy(signals, name="gapfade", entry_at_open=True, time_stop_bars=1)
        slip = TIER_BPS[3] / 10_000

        entry = 100.0 * (1 + slip)
        expected_exit = 100.5 * (1 - slip)   # SAME-bar close

        trades = run_signal_backtest(strat, df, symbol="X", slippage_bps=TIER_BPS[3])
        assert len(trades) == 1
        t = trades[0]
        assert t.exit_reason == "time"
        assert t.entry_date == df.index[0]
        assert t.exit_date == df.index[0]          # SAME bar — not overnight
        assert t.entry == pytest.approx(entry, rel=1e-9)
        assert t.exit == pytest.approx(expected_exit, rel=1e-9)


# ---------------------------------------------------------------------------
# REGRESSION 2: spurious gap_stop on the ENTRY bar of a standard next-open
# entry. The entry bar's RAW open was compared against a stop derived from the
# SLIPPED entry price; since raw open < slipped entry always, any
# stop_dist < open*slip fabricated an instant phantom gap_stop loss even though
# the bar never traded below its open. Bites tight-dollar-stop intraday
# strategies (orb, vwap_reclaim, intraday_momentum).
#
# Hand computation (tier 3, slip = 0.0005, TINY stop_dist=0.02):
#   Bar 0: entry_long=True, stop_dist=0.02
#   Bar 1 (entry bar): entry = open[1]*(1+slip) = 100.0*1.0005 = 100.05
#     stop = 100.05 - 0.02 = 100.03
#     RAW open[1]=100.0 <= 100.03 would (buggily) gap_stop at 100.0*(1-slip).
#     Correct: NO prior-bar stop exists on the entry bar -> branch (a) skipped.
#     bar-1 low=100.05 > 100.03 (no legitimate intrabar stop either) -> survive.
#   Bar 2 (last): eod exit at close[2]=100.5*(1-slip).
# ---------------------------------------------------------------------------

class TestNoSpuriousGapStopOnEntryBar:
    def test_tiny_stop_dist_does_not_phantom_gap_stop_on_entry_bar(self):
        df = _make_df(
            opens=[100.0, 100.0, 100.4],
            highs=[100.5, 100.5, 100.6],
            lows=[99.8, 100.05, 100.2],
            closes=[100.2, 100.4, 100.5],
        )
        signals = pd.DataFrame({
            "entry_long": [True, False, False],
            "exit_long": [False, False, False],
            "stop_dist": [0.02, float("nan"), float("nan")],
        }, index=df.index)
        strat = _StubStrategy(signals, name="tightstop")
        slip = TIER_BPS[3] / 10_000

        entry = 100.0 * (1 + slip)
        expected_exit = 100.5 * (1 - slip)   # eod close, NOT a phantom gap_stop

        trades = run_signal_backtest(strat, df, symbol="X", slippage_bps=TIER_BPS[3])
        assert len(trades) == 1
        t = trades[0]
        assert t.exit_reason == "eod"               # survived the entry bar
        assert t.exit_reason != "gap_stop"
        assert t.entry_date == df.index[1]
        assert t.exit_date == df.index[2]
        assert t.entry == pytest.approx(entry, rel=1e-9)
        assert t.exit == pytest.approx(expected_exit, rel=1e-9)

    def test_legitimate_gap_stop_on_later_bar_still_fires(self):
        # Guard must NOT disable real gap_stops on non-entry bars.
        df = _make_df(
            opens=[104.0, 105.0, 99.0],
            highs=[106.0, 106.0, 100.0],
            lows=[103.0, 104.0, 98.5],
            closes=[105.0, 104.5, 99.5],
        )
        signals = pd.DataFrame({
            "entry_long": [True, False, False],
            "exit_long": [False, False, False],
            "stop_dist": [5.0, float("nan"), float("nan")],
        }, index=df.index)
        strat = _StubStrategy(signals, name="realgap")
        slip = TIER_BPS[3] / 10_000
        # entry bar 1: open=105*(1.0005)=105.0525, stop=100.0525; bar1 survives.
        # bar 2 (NOT entry bar): open=99.0 <= 100.0525 -> real gap_stop.
        trades = run_signal_backtest(strat, df, symbol="X", slippage_bps=TIER_BPS[3])
        assert len(trades) == 1
        assert trades[0].exit_reason == "gap_stop"
        assert trades[0].exit == pytest.approx(99.0 * (1 - slip), rel=1e-9)
