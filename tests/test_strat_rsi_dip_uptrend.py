import numpy as np
import pandas as pd


def _make_ohlcv(n=400, seed=7):
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


def _make_entry_ohlcv():
    """Trending fixture with deliberate RSI dips after EMA200 is warm."""
    n = 360
    idx = pd.date_range("2015-01-01", periods=n, freq="B", name="date")
    close = 100.0 + np.arange(n) * 0.16
    for start in [230, 280, 325]:
        close[start:start + 4] -= np.array([2.0, 4.0, 6.0, 7.0])
    close = pd.Series(close, index=idx)
    open_ = close.shift(1).fillna(close.iloc[0]) + 0.05
    high = np.maximum(open_, close) + 0.35
    low = np.minimum(open_, close) - 0.35
    vol = np.full(n, 2_000_000.0)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
        index=idx,
    )


def _strat():
    from stockslab.strategies.rsi_dip_uptrend import RsiDipUptrend
    return RsiDipUptrend()


class TestCausality:
    def test_generate_causal(self):
        df = _make_ohlcv(400)
        strat = _strat()
        full = strat.generate(df)
        for k in [220, 300, 399]:
            part = strat.generate(df.iloc[:k])
            pd.testing.assert_series_equal(
                full["entry_long"].iloc[:k].reset_index(drop=True),
                part["entry_long"].reset_index(drop=True),
                check_names=False,
            )


class TestEntryRules:
    def test_entry_requires_uptrend_and_rsi_dip(self):
        """entry_long fires only when close>ema200 and rsi14<40."""
        df = _make_entry_ohlcv()
        strat = _strat()
        sigs = strat.generate(df)
        from stockslab.indicators import atr as calc_atr, ema, rsi

        ema200 = ema(df["close"], 200)
        rsi14 = rsi(df["close"], 14)
        atr14 = calc_atr(df, 14)

        uptrend = df["close"] > ema200
        oversold = rsi14 < 40

        expected = uptrend & oversold & atr14.notna()
        assert expected.any(), "fixture must generate real RSI-dip entries"
        pd.testing.assert_series_equal(
            sigs["entry_long"],
            expected.astype(bool),
            check_names=False,
        )

    def test_no_entry_before_ema200_warmup(self):
        """No entry in first 200 bars (ema200 not warm)."""
        df = _make_ohlcv(400)
        strat = _strat()
        sigs = strat.generate(df)
        assert not sigs["entry_long"].iloc[:200].any()

    def test_exit_long_always_false(self):
        """rsi_dip_uptrend has no exit_long signal (exits via target_r / time_stop)."""
        df = _make_ohlcv(400)
        strat = _strat()
        sigs = strat.generate(df)
        assert not sigs["exit_long"].any()

    def test_stop_dist_nan_when_no_entry(self):
        df = _make_ohlcv(400)
        strat = _strat()
        sigs = strat.generate(df)
        no_entry = ~sigs["entry_long"]
        assert sigs.loc[no_entry, "stop_dist"].isna().all()

    def test_stop_dist_is_1p5x_atr(self):
        df = _make_ohlcv(400)
        strat = _strat()
        sigs = strat.generate(df)
        from stockslab.indicators import atr as calc_atr
        atr_vals = calc_atr(df, 14)
        entry_mask = sigs["entry_long"]
        if entry_mask.any():
            np.testing.assert_allclose(
                sigs.loc[entry_mask, "stop_dist"].values,
                (1.5 * atr_vals.loc[entry_mask]).values,
                rtol=1e-10,
            )

    def test_output_columns(self):
        df = _make_ohlcv(100)
        strat = _strat()
        out = strat.generate(df)
        assert list(out.columns) == ["entry_long", "exit_long", "stop_dist"]
        assert len(out) == len(df)
