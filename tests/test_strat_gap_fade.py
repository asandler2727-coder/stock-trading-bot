import numpy as np
import pandas as pd


def _make_ohlcv(n=200, seed=23):
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.standard_normal(n) * 0.5)
    open_ = close + rng.standard_normal(n) * 0.2
    high = np.maximum(open_, close) + abs(rng.standard_normal(n)) * 0.3
    low = np.minimum(open_, close) - abs(rng.standard_normal(n)) * 0.3
    vol = rng.integers(1_000_000, 5_000_000, n).astype(float)
    idx = pd.date_range("2015-01-01", periods=n, freq="B", name="date")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
        index=idx,
    )


def _strat():
    from stockslab.strategies.gap_fade import GapFade
    return GapFade()


class TestCausality:
    def test_generate_causal(self):
        """generate(df[:k]) rows must match generate(df) rows up to k-1.

        entry_at_open=True means the signal for bar t uses only data through
        bar t's open (and prior-bar close/sma); both are available at bar t.
        """
        df = _make_ohlcv(200)
        strat = _strat()
        full = strat.generate(df)
        for k in [100, 150, 199]:
            part = strat.generate(df.iloc[:k])
            pd.testing.assert_series_equal(
                full["entry_long"].iloc[:k].reset_index(drop=True),
                part["entry_long"].reset_index(drop=True),
                check_names=False,
            )


class TestEntryRules:
    def test_entry_fires_on_clean_gap_down(self):
        """Manually construct a bar with a 3% gap-down on an uptrending stock."""
        n = 100
        # Slowly rising close so sma50 lags behind prev_close → uptrend=True
        close = np.linspace(90.0, 110.0, n)
        open_ = close.copy()
        high = close + 1.0
        low = close - 1.0
        vol = np.ones(n) * 1_000_000.0
        idx = pd.date_range("2015-01-01", periods=n, freq="B", name="date")
        df = pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
            index=idx,
        )
        # Bar 80: gap-down open is 3% below bar 79's close
        prev_c = close[79]
        df.iloc[80, df.columns.get_loc("open")] = prev_c * 0.97
        df.iloc[80, df.columns.get_loc("low")] = prev_c * 0.965

        from stockslab.strategies.gap_fade import GapFade
        strat = GapFade()
        sigs = strat.generate(df)
        assert sigs["entry_long"].iloc[80], "should fire at bar 80 (3% gap-down, uptrend)"

    def test_no_entry_on_gap_too_large(self):
        """A 15% gap is outside the 2–10% window."""
        n = 100
        close = np.linspace(90.0, 110.0, n)
        open_ = close.copy()
        high = close + 1.0
        low = close - 1.0
        vol = np.ones(n) * 1_000_000.0
        idx = pd.date_range("2015-01-01", periods=n, freq="B", name="date")
        df = pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
            index=idx,
        )
        prev_c = close[79]
        df.iloc[80, df.columns.get_loc("open")] = prev_c * 0.85   # 15% gap-down
        df.iloc[80, df.columns.get_loc("low")] = prev_c * 0.84

        from stockslab.strategies.gap_fade import GapFade
        strat = GapFade()
        sigs = strat.generate(df)
        assert not sigs["entry_long"].iloc[80]

    def test_no_entry_on_gap_up(self):
        """Only gap-down (open < prev_close) triggers; gap-up must not fire."""
        n = 100
        close = np.linspace(90.0, 110.0, n)
        open_ = close.copy()
        high = close + 1.0
        low = close - 1.0
        vol = np.ones(n) * 1_000_000.0
        idx = pd.date_range("2015-01-01", periods=n, freq="B", name="date")
        df = pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
            index=idx,
        )
        prev_c = close[79]
        df.iloc[80, df.columns.get_loc("open")] = prev_c * 1.03   # gap UP
        df.iloc[80, df.columns.get_loc("high")] = prev_c * 1.04

        from stockslab.strategies.gap_fade import GapFade
        strat = GapFade()
        sigs = strat.generate(df)
        assert not sigs["entry_long"].iloc[80]

    def test_entry_at_open_flag_set(self):
        strat = _strat()
        assert strat.entry_at_open is True

    def test_time_stop_bars_is_1(self):
        strat = _strat()
        assert strat.time_stop_bars == 1

    def test_stop_dist_is_5pct_prev_close(self):
        """stop_dist = 5% of prior close."""
        n = 100
        close = np.linspace(90.0, 110.0, n)
        open_ = close.copy()
        high = close + 1.0
        low = close - 1.0
        vol = np.ones(n) * 1_000_000.0
        idx = pd.date_range("2015-01-01", periods=n, freq="B", name="date")
        df = pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
            index=idx,
        )
        prev_c = close[79]
        df.iloc[80, df.columns.get_loc("open")] = prev_c * 0.97
        df.iloc[80, df.columns.get_loc("low")] = prev_c * 0.965

        from stockslab.strategies.gap_fade import GapFade
        strat = GapFade()
        sigs = strat.generate(df)
        assert sigs["entry_long"].iloc[80], "need entry to fire for stop_dist check"
        expected_stop = 0.05 * prev_c
        np.testing.assert_allclose(sigs["stop_dist"].iloc[80], expected_stop, rtol=1e-9)

    def test_output_columns(self):
        df = _make_ohlcv(100)
        strat = _strat()
        out = strat.generate(df)
        assert list(out.columns) == ["entry_long", "exit_long", "stop_dist"]
        assert len(out) == len(df)
