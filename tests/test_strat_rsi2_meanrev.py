import numpy as np
import pandas as pd


def _make_ohlcv(n=300, seed=11):
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
    from stockslab.strategies.rsi2_meanrev import Rsi2Meanrev
    return Rsi2Meanrev()


class TestCausality:
    def test_generate_causal(self):
        df = _make_ohlcv(300)
        strat = _strat()
        full = strat.generate(df)
        for k in [220, 280]:
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


class TestEntryRules:
    def test_entry_fires_on_oversold_above_sma200(self):
        """entry fires exactly when close>sma200 AND rsi2<10."""
        df = _make_ohlcv(300)
        strat = _strat()
        sigs = strat.generate(df)
        from stockslab.indicators import rsi, sma, atr as calc_atr
        sma200 = sma(df["close"], 200)
        rsi2 = rsi(df["close"], 2)
        atr14 = calc_atr(df, 14)
        expected = (df["close"] > sma200) & (rsi2 < 10) & atr14.notna()
        # Only compare where all indicators are warm
        warm = sma200.notna() & rsi2.notna() & atr14.notna()
        pd.testing.assert_series_equal(
            sigs["entry_long"][warm],
            expected[warm].astype(bool),
            check_names=False,
        )

    def test_no_entry_before_sma200_warmup(self):
        df = _make_ohlcv(300)
        strat = _strat()
        sigs = strat.generate(df)
        assert not sigs["entry_long"].iloc[:200].any()

    def test_exit_fires_on_rsi_recovery_or_sma5_cross(self):
        """exit_long fires when rsi2>70 OR close>sma5."""
        df = _make_ohlcv(300)
        strat = _strat()
        sigs = strat.generate(df)
        from stockslab.indicators import rsi, sma
        rsi2 = rsi(df["close"], 2)
        sma5 = sma(df["close"], 5)
        expected = (rsi2 > 70) | (df["close"] > sma5)
        warm = rsi2.notna() & sma5.notna()
        pd.testing.assert_series_equal(
            sigs["exit_long"][warm],
            expected[warm].astype(bool),
            check_names=False,
        )

    def test_stop_dist_is_2p5x_atr(self):
        df = _make_ohlcv(300)
        strat = _strat()
        sigs = strat.generate(df)
        from stockslab.indicators import atr as calc_atr
        atr14 = calc_atr(df, 14)
        entry_mask = sigs["entry_long"]
        if entry_mask.any():
            np.testing.assert_allclose(
                sigs.loc[entry_mask, "stop_dist"].values,
                (2.5 * atr14.loc[entry_mask]).values,
                rtol=1e-10,
            )

    def test_output_columns(self):
        df = _make_ohlcv(100)
        strat = _strat()
        out = strat.generate(df)
        assert list(out.columns) == ["entry_long", "exit_long", "stop_dist"]
        assert len(out) == len(df)
