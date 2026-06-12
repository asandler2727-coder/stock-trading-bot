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


def _strat():
    from stockslab.strategies.ema_pullback import EmaPullback
    return EmaPullback()


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
    def test_entry_requires_all_three_conditions(self):
        """entry_long only fires when uptrend AND low<=ema20 AND rsi14<40."""
        df = _make_ohlcv(400)
        strat = _strat()
        sigs = strat.generate(df)
        from stockslab.indicators import ema, rsi

        ema20 = ema(df["close"], 20)
        ema50 = ema(df["close"], 50)
        ema200 = ema(df["close"], 200)
        rsi14 = rsi(df["close"], 14)

        uptrend = (ema50 > ema200) & (df["close"] > ema50)
        pullback = df["low"] <= ema20
        oversold = rsi14 < 40

        expected = uptrend & pullback & oversold
        # Expected may be NaN-masked; ignore pre-warmup
        warm_idx = df.index[expected.notna() & uptrend.notna()]
        pd.testing.assert_series_equal(
            sigs["entry_long"].loc[warm_idx],
            expected.loc[warm_idx].astype(bool),
            check_names=False,
        )

    def test_no_entry_before_ema200_warmup(self):
        """No entry in first 200 bars (ema200 not warm)."""
        df = _make_ohlcv(400)
        strat = _strat()
        sigs = strat.generate(df)
        assert not sigs["entry_long"].iloc[:200].any()

    def test_exit_long_always_false(self):
        """ema_pullback has no exit_long signal (exits via target_r / time_stop)."""
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
