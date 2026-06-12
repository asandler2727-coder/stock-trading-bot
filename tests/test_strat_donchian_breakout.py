import numpy as np
import pandas as pd
import pytest


def _make_ohlcv(n=300, seed=42):
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
    from stockslab.strategies.donchian_breakout import DonchianBreakout
    return DonchianBreakout()


class TestCausality:
    def test_generate_causal(self):
        df = _make_ohlcv(300)
        strat = _strat()
        full = strat.generate(df)
        for k in [100, 200, 299]:
            part = strat.generate(df.iloc[:k])
            pd.testing.assert_series_equal(
                full["entry_long"].iloc[:k].reset_index(drop=True),
                part["entry_long"].reset_index(drop=True),
                check_names=False,
            )
            pd.testing.assert_series_equal(
                full["exit_long"].iloc[:k].reset_index(drop=True),
                part["exit_long"].reset_index(drop=True),
                check_names=False,
            )
            # stop_dist: compare non-NaN positions
            f_sd = full["stop_dist"].iloc[:k].values
            p_sd = part["stop_dist"].values
            mask = ~(np.isnan(f_sd) | np.isnan(p_sd))
            if mask.any():
                np.testing.assert_allclose(f_sd[mask], p_sd[mask], rtol=1e-10)


class TestEntryRules:
    def test_entry_requires_55bar_breakout(self):
        """Entry only fires when close exceeds the prior bar's 55-bar Donchian high."""
        df = _make_ohlcv(200)
        strat = _strat()
        sigs = strat.generate(df)
        from stockslab.indicators import donchian_high
        dh_prev = donchian_high(df, 55).shift(1)
        # Every entry bar must satisfy close > prior donchian high
        entry_bars = sigs["entry_long"]
        for i in df.index[entry_bars]:
            assert df.loc[i, "close"] > dh_prev.loc[i]

    def test_no_entry_before_warmup(self):
        """No entry in first 55 bars (donchian not yet warm)."""
        df = _make_ohlcv(200)
        strat = _strat()
        sigs = strat.generate(df)
        assert not sigs["entry_long"].iloc[:56].any()

    def test_exit_uses_20bar_donchian_low(self):
        """Exit fires when close drops below prior bar's 20-bar Donchian low."""
        df = _make_ohlcv(200)
        strat = _strat()
        sigs = strat.generate(df)
        from stockslab.indicators import donchian_low
        dl_prev = donchian_low(df, 20).shift(1)
        exit_bars = sigs["exit_long"]
        for i in df.index[exit_bars]:
            assert df.loc[i, "close"] < dl_prev.loc[i]

    def test_stop_dist_is_2x_atr(self):
        """stop_dist on entry bars equals 2*ATR(14)."""
        df = _make_ohlcv(200)
        strat = _strat()
        sigs = strat.generate(df)
        from stockslab.indicators import atr as calc_atr
        atr_vals = calc_atr(df, 14)
        entry_mask = sigs["entry_long"]
        if entry_mask.any():
            np.testing.assert_allclose(
                sigs.loc[entry_mask, "stop_dist"].values,
                (2.0 * atr_vals.loc[entry_mask]).values,
                rtol=1e-10,
            )

    def test_stop_dist_nan_when_no_entry(self):
        df = _make_ohlcv(200)
        strat = _strat()
        sigs = strat.generate(df)
        no_entry = ~sigs["entry_long"]
        assert sigs.loc[no_entry, "stop_dist"].isna().all()

    def test_output_shape_and_columns(self):
        df = _make_ohlcv(100)
        strat = _strat()
        out = strat.generate(df)
        assert list(out.columns) == ["entry_long", "exit_long", "stop_dist"]
        assert len(out) == len(df)
        assert (out.index == df.index).all()
