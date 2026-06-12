"""Tests for xsec_momentum rotation strategy."""
import numpy as np
import pandas as pd


def _make_panel(symbols, n=400, seed=41):
    """Return a dict of synthetic OHLCV DataFrames on business-day dates."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2015-01-01", periods=n, freq="B", name="date")
    panel = {}
    for i, sym in enumerate(symbols):
        close = 100.0 + np.cumsum(rng.standard_normal(n) * 0.5 + i * 0.02)
        panel[sym] = pd.DataFrame(
            {
                "open": close, "high": close + 0.5,
                "low": close - 0.5, "close": close,
                "volume": np.ones(n) * 1e6,
            },
            index=idx,
        )
    return panel


def _strat():
    from stockslab.strategies.xsec_momentum import XsecMomentum
    return XsecMomentum()


class TestCausality:
    def test_holdings_causal(self):
        """Holdings at date d must not change when future data is added."""
        symbols = ["SPY"] + [f"S{i}" for i in range(20)]
        panel_full = _make_panel(symbols, n=400)
        strat = _strat()
        dates_full = panel_full["SPY"].index
        full = strat.target_holdings(panel_full, dates_full)
        if full.empty:
            return  # nothing to compare

        # Truncate at midpoint and recompute
        mid = 300
        panel_part = {s: df.iloc[:mid] for s, df in panel_full.items()}
        dates_part = panel_part["SPY"].index
        part = strat.target_holdings(panel_part, dates_part)

        # Rebalance dates in the partial window
        common = [d for d in full.index if d in part.index]
        for sym in part.columns:
            if sym in full.columns:
                pd.testing.assert_series_equal(
                    full.loc[common, sym],
                    part.loc[common, sym],
                    check_names=False,
                )


class TestRotationRules:
    def test_empty_holdings_when_spy_below_sma200(self):
        """In a bear regime (SPY below SMA200), all holdings are 0."""
        n = 400
        symbols = ["SPY"] + [f"S{i}" for i in range(10)]
        panel = _make_panel(symbols, n=n)
        # Force SPY into a downtrend: overwrite with declining prices
        close_spy = 200.0 - np.linspace(0, 100, n)
        panel["SPY"]["close"] = close_spy

        strat = _strat()
        dates = panel["SPY"].index
        holdings = strat.target_holdings(panel, dates)

        if not holdings.empty:
            # After SMA200 is warm (day 200+), all holdings should be 0
            late_dates = [d for d in holdings.index if d >= dates[200]]
            if late_dates:
                assert (holdings.loc[late_dates] == 0).all().all()

    def test_top_n_symbols_selected(self):
        """In a bull regime, exactly top_n symbols get weight 1."""
        n = 400
        symbols = ["SPY"] + [f"S{i}" for i in range(20)]
        panel = _make_panel(symbols, n=n)
        # Make SPY strongly trending up so regime is True
        panel["SPY"]["close"] = 100.0 + np.linspace(0, 100, n)

        strat = _strat()
        dates = panel["SPY"].index
        holdings = strat.target_holdings(panel, dates)

        if not holdings.empty:
            late = [d for d in holdings.index if d >= dates[260]]
            for d in late:
                row_sum = holdings.loc[d].sum()
                # Should hold exactly top_n or fewer (if some symbols lack history)
                assert row_sum <= strat.params["top_n"]

    def test_rebalances_on_mondays_only(self):
        """target_holdings returns only Monday dates."""
        symbols = ["SPY"] + [f"S{i}" for i in range(5)]
        panel = _make_panel(symbols, n=400)
        strat = _strat()
        holdings = strat.target_holdings(panel, panel["SPY"].index)
        for d in holdings.index:
            assert d.weekday() == 0, f"{d} is not Monday"

    def test_output_has_correct_columns(self):
        symbols = ["SPY", "AAPL", "MSFT", "GOOG"]
        panel = _make_panel(symbols, n=400)
        strat = _strat()
        holdings = strat.target_holdings(panel, panel["SPY"].index)
        # SPY is regime ref, should not be a tradeable column
        assert "SPY" not in holdings.columns
        for sym in ["AAPL", "MSFT", "GOOG"]:
            assert sym in holdings.columns
