import numpy as np
import pandas as pd


def _make_ohlcv(n=500, seed=17):
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
    from stockslab.strategies.high52_breakout import High52Breakout
    return High52Breakout()


class TestCausality:
    def test_generate_causal(self):
        df = _make_ohlcv(500)
        strat = _strat()
        full = strat.generate(df)
        for k in [300, 450, 499]:
            part = strat.generate(df.iloc[:k])
            pd.testing.assert_series_equal(
                full["entry_long"].iloc[:k].reset_index(drop=True),
                part["entry_long"].reset_index(drop=True),
                check_names=False,
            )


class TestEntryRules:
    def test_no_entry_before_warmup(self):
        """No entry until 252+1 bars of data (rolling_high shift needs 253 bars)."""
        df = _make_ohlcv(500)
        strat = _strat()
        sigs = strat.generate(df)
        assert not sigs["entry_long"].iloc[:253].any()

    def test_entry_requires_52week_high_and_volume(self):
        """Build a synthetic bar that clears both conditions exactly."""
        n = 300
        rng = np.random.default_rng(99)
        close = np.ones(n) * 100.0
        high = np.ones(n) * 101.0
        low = np.ones(n) * 99.0
        open_ = np.ones(n) * 100.0
        vol = np.ones(n) * 1_000_000.0
        idx = pd.date_range("2015-01-01", periods=n, freq="B", name="date")
        df = pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
            index=idx,
        )
        # Bar at index 260: high = 105 (new 252-bar high), volume = 2M (> 1.5 * 1M avg)
        df.iloc[260, df.columns.get_loc("high")] = 105.0
        df.iloc[260, df.columns.get_loc("volume")] = 2_000_000.0

        from stockslab.strategies.high52_breakout import High52Breakout
        strat = High52Breakout()
        sigs = strat.generate(df)
        assert sigs["entry_long"].iloc[260], "should fire at bar 260"
        # Bar 261 should NOT fire (high resets to 101, not a new high over prior window)
        assert not sigs["entry_long"].iloc[261], "should not fire at bar 261"

    def test_stop_dist_is_2x_atr(self):
        df = _make_ohlcv(500)
        strat = _strat()
        sigs = strat.generate(df)
        from stockslab.indicators import atr as calc_atr
        atr14 = calc_atr(df, 14)
        entry_mask = sigs["entry_long"]
        if entry_mask.any():
            np.testing.assert_allclose(
                sigs.loc[entry_mask, "stop_dist"].values,
                (2.0 * atr14.loc[entry_mask]).values,
                rtol=1e-10,
            )

    def test_output_columns(self):
        df = _make_ohlcv(100)
        strat = _strat()
        out = strat.generate(df)
        assert list(out.columns) == ["entry_long", "exit_long", "stop_dist"]
        assert len(out) == len(df)
