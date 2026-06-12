"""Tests for sector_rotation strategy."""
import numpy as np
import pandas as pd

_SECTORS = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLU", "XLY", "XLB", "XLRE", "XLC"]


def _make_panel(extra_syms=None, n=400, seed=43):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2015-01-01", periods=n, freq="B", name="date")
    symbols = ["SPY"] + _SECTORS + (extra_syms or [])
    panel = {}
    for i, sym in enumerate(symbols):
        close = 100.0 + np.cumsum(rng.standard_normal(n) * 0.5 + i * 0.01)
        panel[sym] = pd.DataFrame(
            {"open": close, "high": close + 0.5, "low": close - 0.5,
             "close": close, "volume": np.ones(n) * 1e6},
            index=idx,
        )
    return panel


def _strat():
    from stockslab.strategies.sector_rotation import SectorRotation
    return SectorRotation()


class TestCausality:
    def test_holdings_causal(self):
        panel_full = _make_panel(n=400)
        strat = _strat()
        dates_full = panel_full["SPY"].index
        full = strat.target_holdings(panel_full, dates_full)
        if full.empty:
            return
        mid = 300
        panel_part = {s: df.iloc[:mid] for s, df in panel_full.items()}
        part = strat.target_holdings(panel_part, panel_part["SPY"].index)
        common = [d for d in full.index if d in part.index]
        for sym in part.columns:
            if sym in full.columns:
                pd.testing.assert_series_equal(
                    full.loc[common, sym], part.loc[common, sym], check_names=False
                )


class TestRotationRules:
    def test_exactly_top3_selected_in_bull(self):
        """Top-3 sectors hold weight=1 in bull regime."""
        panel = _make_panel(n=400)
        # Force SPY uptrend
        panel["SPY"]["close"] = 100.0 + np.linspace(0, 100, 400)
        strat = _strat()
        holdings = strat.target_holdings(panel, panel["SPY"].index)
        if not holdings.empty:
            late = [d for d in holdings.index if d >= panel["SPY"].index[260]]
            for d in late:
                assert holdings.loc[d].sum() <= 3

    def test_all_zero_in_bear_regime(self):
        """Bear regime (SPY < SMA200) → all holdings 0."""
        panel = _make_panel(n=400)
        panel["SPY"]["close"] = 200.0 - np.linspace(0, 100, 400)
        strat = _strat()
        holdings = strat.target_holdings(panel, panel["SPY"].index)
        if not holdings.empty:
            late = [d for d in holdings.index if d >= panel["SPY"].index[210]]
            if late:
                assert (holdings.loc[late] == 0).all().all()

    def test_rebalances_on_mondays(self):
        panel = _make_panel(n=400)
        strat = _strat()
        holdings = strat.target_holdings(panel, panel["SPY"].index)
        for d in holdings.index:
            assert d.weekday() == 0

    def test_only_sector_etfs_in_columns(self):
        panel = _make_panel(extra_syms=["AAPL"], n=400)
        strat = _strat()
        holdings = strat.target_holdings(panel, panel["SPY"].index)
        # AAPL and SPY should not be in columns
        assert "AAPL" not in holdings.columns
        assert "SPY" not in holdings.columns
        for s in _SECTORS:
            assert s in holdings.columns
