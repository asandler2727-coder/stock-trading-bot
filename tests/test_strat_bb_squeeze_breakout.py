import numpy as np
import pandas as pd


def _make_ohlcv(n=600, seed=13):
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
    from stockslab.strategies.bb_squeeze_breakout import BbSqueezeBreakout
    return BbSqueezeBreakout()


class TestCausality:
    def test_generate_causal(self):
        df = _make_ohlcv(600)
        strat = _strat()
        full = strat.generate(df)
        for k in [300, 500, 599]:
            part = strat.generate(df.iloc[:k])
            pd.testing.assert_series_equal(
                full["entry_long"].iloc[:k].reset_index(drop=True),
                part["entry_long"].reset_index(drop=True),
                check_names=False,
            )


class TestEntryRules:
    def test_no_entry_before_lookback_warmup(self):
        """No entry in first 252+20 bars (both bb and squeeze lookback not warm)."""
        df = _make_ohlcv(600)
        strat = _strat()
        sigs = strat.generate(df)
        # lookback=252 + bb_n=20 warmup → first possible entry at bar 272+
        assert not sigs["entry_long"].iloc[:272].any()

    def test_entry_requires_prior_squeeze_and_breakout(self):
        """Each entry bar: prior bar was in squeeze AND close > bb_upper today."""
        df = _make_ohlcv(600)
        strat = _strat()
        sigs = strat.generate(df)
        from stockslab.indicators import bb
        _, bb_upper, _, bb_width = bb(df["close"], 20, 2.0)
        width_thresh = bb_width.rolling(252, min_periods=252).quantile(0.15)
        in_squeeze = (bb_width <= width_thresh) & width_thresh.notna()
        prior_squeeze = in_squeeze.shift(1).fillna(False)
        above_upper = df["close"] > bb_upper

        entry_bars = df.index[sigs["entry_long"]]
        for d in entry_bars:
            assert prior_squeeze.loc[d], f"{d}: prior bar not in squeeze"
            assert above_upper.loc[d], f"{d}: close not above bb_upper"

    def test_stop_dist_is_2x_atr(self):
        df = _make_ohlcv(600)
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

    def test_exit_long_always_false(self):
        df = _make_ohlcv(300)
        strat = _strat()
        sigs = strat.generate(df)
        assert not sigs["exit_long"].any()

    def test_output_columns(self):
        df = _make_ohlcv(100)
        strat = _strat()
        out = strat.generate(df)
        assert list(out.columns) == ["entry_long", "exit_long", "stop_dist"]
        assert len(out) == len(df)
