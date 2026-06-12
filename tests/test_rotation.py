"""Tests for run_rotation_backtest (Task A5).

Hand-computed expected values for each semantic:
  - Membership change at rebalance d fills at next open for adds AND drops
  - Held-through positions (same member on consecutive rebalances) are untouched
  - Each add = one Trade with pct_return computed from buy/sell prices
  - r_multiple for rotation trades = pct_return / 0.10 (10%-notional R proxy)
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from stockslab.engine import Trade, run_rotation_backtest
from stockslab.strategies.base import RotationStrategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_df(dates, opens, highs=None, lows=None, closes=None, volumes=None):
    """Build a minimal OHLCV DataFrame with a DatetimeIndex named 'date'."""
    n = len(dates)
    opens = list(opens)
    closes = closes if closes is not None else opens
    highs = highs if highs is not None else [max(o, c) for o, c in zip(opens, closes)]
    lows = lows if lows is not None else [min(o, c) for o, c in zip(opens, closes)]
    volumes = volumes if volumes is not None else [1_000_000] * n
    idx = pd.DatetimeIndex(dates, name="date")
    return pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        },
        index=idx,
        dtype=float,
    )


class _FixedRotationStrategy(RotationStrategy):
    """Test stub: emits a preset holdings DataFrame."""

    def __init__(self, holdings_df: pd.DataFrame):
        super().__init__(name="test_rotation")
        self._holdings = holdings_df

    def target_holdings(self, panel, dates):
        return self._holdings


# ---------------------------------------------------------------------------
# Test 1: Simple add then exit — one symbol added at rebalance d0, sold at d1
# ---------------------------------------------------------------------------

class TestSimpleAddAndExit:
    """
    Dates:  d0=Mon, d1=Mon next week
    Symbols: A

    Rebalance schedule:
      d0: {A: 1}  -> add A; fills at open[d0+1]
      d1: {A: 0}  -> drop A; fills at open[d1+1]

    OHLCV for A:
      d0:         open=100, close=100
      d0+1 (buy): open=102  <- entry price * (1 + slip)
      ...bars in between...
      d1:         open=110, close=110
      d1+1 (sell):open=115  <- exit price * (1 - slip)

    slippage_bps_map = {A: 3}  -> slip = 0.0003

    entry = 102 * 1.0003 = 102.0306
    exit  = 115 * 0.9997 = 114.9655

    pct_return = (exit - entry) / entry
               = (114.9655 - 102.0306) / 102.0306
               ≈ 0.126817...

    r_multiple = pct_return / 0.10
    """

    def setup_method(self):
        dates_A = pd.to_datetime([
            "2020-01-06",  # d0 (Mon): rebalance, signal date
            "2020-01-07",  # d0+1: buy fills here (open=102)
            "2020-01-08",
            "2020-01-09",
            "2020-01-10",
            "2020-01-13",  # d1 (Mon): next rebalance, signal date
            "2020-01-14",  # d1+1: sell fills here (open=115)
        ])
        self.df_A = _make_df(
            dates_A,
            opens=[100, 102, 103, 104, 105, 110, 115],
            closes=[100, 101, 103, 104, 106, 110, 116],
        )
        self.panel = {"A": self.df_A}

        # Holdings: add A at d0, remove A at d1
        reb_dates = pd.DatetimeIndex(["2020-01-06", "2020-01-13"], name="date")
        holdings = pd.DataFrame(
            {"A": [1, 0]},
            index=reb_dates,
        )
        self.strategy = _FixedRotationStrategy(holdings)
        self.slippage_map = {"A": 3}

    def test_produces_one_trade(self):
        trades = run_rotation_backtest(self.strategy, self.panel, self.slippage_map)
        assert len(trades) == 1

    def test_trade_symbol(self):
        trades = run_rotation_backtest(self.strategy, self.panel, self.slippage_map)
        assert trades[0].symbol == "A"

    def test_entry_date_is_day_after_rebalance(self):
        """Entry fills at the open of the bar AFTER the rebalance date."""
        trades = run_rotation_backtest(self.strategy, self.panel, self.slippage_map)
        assert trades[0].entry_date == pd.Timestamp("2020-01-07")

    def test_exit_date_is_day_after_drop_rebalance(self):
        """Exit fills at the open of the bar AFTER the drop rebalance date."""
        trades = run_rotation_backtest(self.strategy, self.panel, self.slippage_map)
        assert trades[0].exit_date == pd.Timestamp("2020-01-14")

    def test_entry_price_with_slippage(self):
        trades = run_rotation_backtest(self.strategy, self.panel, self.slippage_map)
        expected_entry = 102 * (1 + 3 / 10_000)
        assert abs(trades[0].entry - expected_entry) < 1e-8

    def test_exit_price_with_slippage(self):
        trades = run_rotation_backtest(self.strategy, self.panel, self.slippage_map)
        expected_exit = 115 * (1 - 3 / 10_000)
        assert abs(trades[0].exit - expected_exit) < 1e-8

    def test_pct_return_hand_computed(self):
        entry = 102 * (1 + 3 / 10_000)
        exit_ = 115 * (1 - 3 / 10_000)
        expected_pct = (exit_ - entry) / entry
        trades = run_rotation_backtest(self.strategy, self.panel, self.slippage_map)
        assert abs(trades[0].pct_return - expected_pct) < 1e-8

    def test_r_multiple_is_pct_return_over_010(self):
        """r_multiple = pct_return / 0.10 (10%-notional R proxy)."""
        trades = run_rotation_backtest(self.strategy, self.panel, self.slippage_map)
        expected_r = trades[0].pct_return / 0.10
        assert abs(trades[0].r_multiple - expected_r) < 1e-8

    def test_exit_reason_is_rotation(self):
        trades = run_rotation_backtest(self.strategy, self.panel, self.slippage_map)
        assert trades[0].exit_reason == "rotation"


# ---------------------------------------------------------------------------
# Test 2: Held-through position — symbol in portfolio for two consecutive
#         rebalances without being dropped should generate exactly ONE trade.
# ---------------------------------------------------------------------------

class TestHeldThroughNoExtraTrade:
    """
    Rebalances: d0={A:1}, d1={A:1}, d2={A:0}
    Expect: exactly 1 trade for A (entered after d0, exited after d2).
    """

    def setup_method(self):
        dates_A = pd.to_datetime([
            "2020-01-06",  # d0: rebalance — add A
            "2020-01-07",  # buy fills (open=100)
            "2020-01-13",  # d1: rebalance — A still held, no action
            "2020-01-14",  # this open is NOT used for A (held)
            "2020-01-20",  # d2: rebalance — drop A
            "2020-01-21",  # sell fills (open=120)
        ])
        self.df_A = _make_df(
            dates_A,
            opens=[99, 100, 109, 110, 119, 120],
            closes=[99, 101, 110, 111, 120, 121],
        )
        self.panel = {"A": self.df_A}

        reb_dates = pd.DatetimeIndex(
            ["2020-01-06", "2020-01-13", "2020-01-20"], name="date"
        )
        holdings = pd.DataFrame(
            {"A": [1, 1, 0]},
            index=reb_dates,
        )
        self.strategy = _FixedRotationStrategy(holdings)
        self.slippage_map = {"A": 3}

    def test_exactly_one_trade(self):
        trades = run_rotation_backtest(self.strategy, self.panel, self.slippage_map)
        assert len(trades) == 1

    def test_entry_date(self):
        trades = run_rotation_backtest(self.strategy, self.panel, self.slippage_map)
        assert trades[0].entry_date == pd.Timestamp("2020-01-07")

    def test_exit_date(self):
        trades = run_rotation_backtest(self.strategy, self.panel, self.slippage_map)
        assert trades[0].exit_date == pd.Timestamp("2020-01-21")

    def test_entry_price(self):
        trades = run_rotation_backtest(self.strategy, self.panel, self.slippage_map)
        expected_entry = 100 * (1 + 3 / 10_000)
        assert abs(trades[0].entry - expected_entry) < 1e-8

    def test_exit_price(self):
        trades = run_rotation_backtest(self.strategy, self.panel, self.slippage_map)
        expected_exit = 120 * (1 - 3 / 10_000)
        assert abs(trades[0].exit - expected_exit) < 1e-8


# ---------------------------------------------------------------------------
# Test 3: Multiple symbols — two symbols, different fates
# ---------------------------------------------------------------------------

class TestMultiSymbolRotation:
    """
    Rebalance d0: {A:1, B:1}
    Rebalance d1: {A:0, B:1}  -> A dropped, B continues

    Expect: 1 trade for A, 0 for B (still open after d1 is the last rebalance)
    but if there's a final eod exit for B...

    For simplicity: 3 rebalances so B exits cleanly.
    d0: add A, B
    d1: drop A, keep B
    d2: drop B
    """

    def setup_method(self):
        dates_common = pd.to_datetime([
            "2020-01-06",  # d0
            "2020-01-07",  # fills d0
            "2020-01-13",  # d1
            "2020-01-14",  # fills d1
            "2020-01-20",  # d2
            "2020-01-21",  # fills d2
        ])
        self.df_A = _make_df(
            dates_common,
            opens=[100, 101, 110, 111, 120, 121],
            closes=[100, 102, 111, 112, 121, 122],
        )
        self.df_B = _make_df(
            dates_common,
            opens=[200, 202, 210, 212, 220, 222],
            closes=[200, 203, 211, 213, 221, 223],
        )
        self.panel = {"A": self.df_A, "B": self.df_B}

        reb_dates = pd.DatetimeIndex(
            ["2020-01-06", "2020-01-13", "2020-01-20"], name="date"
        )
        holdings = pd.DataFrame(
            {"A": [1, 0, 0], "B": [1, 1, 0]},
            index=reb_dates,
        )
        self.strategy = _FixedRotationStrategy(holdings)
        self.slippage_map = {"A": 3, "B": 1}

    def test_exactly_two_trades(self):
        trades = run_rotation_backtest(self.strategy, self.panel, self.slippage_map)
        assert len(trades) == 2

    def test_trade_symbols(self):
        trades = run_rotation_backtest(self.strategy, self.panel, self.slippage_map)
        syms = {t.symbol for t in trades}
        assert syms == {"A", "B"}

    def test_a_entry_and_exit_dates(self):
        trades = run_rotation_backtest(self.strategy, self.panel, self.slippage_map)
        a = next(t for t in trades if t.symbol == "A")
        assert a.entry_date == pd.Timestamp("2020-01-07")
        assert a.exit_date == pd.Timestamp("2020-01-14")

    def test_b_entry_and_exit_dates(self):
        trades = run_rotation_backtest(self.strategy, self.panel, self.slippage_map)
        b = next(t for t in trades if t.symbol == "B")
        assert b.entry_date == pd.Timestamp("2020-01-07")
        assert b.exit_date == pd.Timestamp("2020-01-21")

    def test_a_slippage_tier3(self):
        """A uses tier 3 = 3 bps."""
        trades = run_rotation_backtest(self.strategy, self.panel, self.slippage_map)
        a = next(t for t in trades if t.symbol == "A")
        expected_entry = 101 * (1 + 3 / 10_000)
        expected_exit = 111 * (1 - 3 / 10_000)
        assert abs(a.entry - expected_entry) < 1e-8
        assert abs(a.exit - expected_exit) < 1e-8

    def test_b_slippage_tier1(self):
        """B uses tier 1 = 1 bp."""
        trades = run_rotation_backtest(self.strategy, self.panel, self.slippage_map)
        b = next(t for t in trades if t.symbol == "B")
        expected_entry = 202 * (1 + 1 / 10_000)
        expected_exit = 222 * (1 - 1 / 10_000)
        assert abs(b.entry - expected_entry) < 1e-8
        assert abs(b.exit - expected_exit) < 1e-8


# ---------------------------------------------------------------------------
# Test 4: No fill bar after rebalance (rebalance on last bar) — eod
# ---------------------------------------------------------------------------

class TestRebalanceOnLastBar:
    """
    If a symbol is added at the LAST rebalance date and there is no next bar,
    the trade cannot be entered (skip; no Trade emitted).
    Conversely, if a symbol is in the portfolio and the data ends while it is
    still held, it should get an eod exit at the last close.
    """

    def setup_method(self):
        # Only 2 bars: d0 and d0+1. Rebalance at d0 adds A.
        # A is bought at d0+1 open. No d1 rebalance, so A is still held.
        # At end of data, eod exit at last close.
        dates_A = pd.to_datetime(["2020-01-06", "2020-01-07"])
        self.df_A = _make_df(
            dates_A,
            opens=[100, 110],
            closes=[105, 115],
        )
        self.panel = {"A": self.df_A}

        reb_dates = pd.DatetimeIndex(["2020-01-06"], name="date")
        holdings = pd.DataFrame({"A": [1]}, index=reb_dates)
        self.strategy = _FixedRotationStrategy(holdings)
        self.slippage_map = {"A": 3}

    def test_eod_exit_produces_one_trade(self):
        trades = run_rotation_backtest(self.strategy, self.panel, self.slippage_map)
        assert len(trades) == 1

    def test_eod_exit_reason(self):
        trades = run_rotation_backtest(self.strategy, self.panel, self.slippage_map)
        assert trades[0].exit_reason == "eod"

    def test_eod_exit_price_is_last_close_with_slip(self):
        trades = run_rotation_backtest(self.strategy, self.panel, self.slippage_map)
        expected_exit = 115 * (1 - 3 / 10_000)
        assert abs(trades[0].exit - expected_exit) < 1e-8


# ---------------------------------------------------------------------------
# Test 5: Add signal on last bar — no trade (no fill bar available)
# ---------------------------------------------------------------------------

class TestAddOnLastBarNoTrade:
    """
    Rebalance on last bar of data: add A.
    No next bar to fill → no Trade emitted.
    """

    def setup_method(self):
        # d0 is the ONLY bar; rebalance says add A but there's no d0+1
        dates_A = pd.to_datetime(["2020-01-06"])
        self.df_A = _make_df(dates_A, opens=[100], closes=[105])
        self.panel = {"A": self.df_A}

        reb_dates = pd.DatetimeIndex(["2020-01-06"], name="date")
        holdings = pd.DataFrame({"A": [1]}, index=reb_dates)
        self.strategy = _FixedRotationStrategy(holdings)
        self.slippage_map = {"A": 3}

    def test_no_trade_when_no_fill_bar(self):
        trades = run_rotation_backtest(self.strategy, self.panel, self.slippage_map)
        assert len(trades) == 0


# ---------------------------------------------------------------------------
# Test 6: r_multiple sign — losing rotation trade
# ---------------------------------------------------------------------------

class TestLosingRotationTrade:
    """
    A is added, price drops.
    pct_return < 0 → r_multiple < 0.
    """

    def setup_method(self):
        dates_A = pd.to_datetime([
            "2020-01-06",
            "2020-01-07",  # buy open=100
            "2020-01-13",
            "2020-01-14",  # sell open=90
        ])
        self.df_A = _make_df(
            dates_A,
            opens=[99, 100, 91, 90],
            closes=[99, 100, 91, 90],
        )
        self.panel = {"A": self.df_A}

        reb_dates = pd.DatetimeIndex(["2020-01-06", "2020-01-13"], name="date")
        holdings = pd.DataFrame({"A": [1, 0]}, index=reb_dates)
        self.strategy = _FixedRotationStrategy(holdings)
        self.slippage_map = {"A": 3}

    def test_losing_pct_return(self):
        trades = run_rotation_backtest(self.strategy, self.panel, self.slippage_map)
        assert trades[0].pct_return < 0

    def test_losing_r_multiple(self):
        trades = run_rotation_backtest(self.strategy, self.panel, self.slippage_map)
        assert trades[0].r_multiple < 0

    def test_r_multiple_equals_pct_over_010(self):
        trades = run_rotation_backtest(self.strategy, self.panel, self.slippage_map)
        t = trades[0]
        assert abs(t.r_multiple - t.pct_return / 0.10) < 1e-10
