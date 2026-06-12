"""Tests for levered_etf_meanrev strategy.

QQQ context is provided via strategy.context rather than cache — no network or
file I/O needed in tests.
"""
import numpy as np
import pandas as pd


def _make_ohlcv(n=300, seed=31, start="2015-01-01", trend="flat"):
    rng = np.random.default_rng(seed)
    if trend == "up":
        close = 100.0 + np.linspace(0, 50, n) + rng.standard_normal(n) * 0.3
    else:
        close = 100.0 + rng.standard_normal(n) * 0.5
    open_ = close + rng.standard_normal(n) * 0.2
    high = np.maximum(open_, close) + abs(rng.standard_normal(n)) * 0.3
    low = np.minimum(open_, close) - abs(rng.standard_normal(n)) * 0.3
    vol = rng.integers(1_000_000, 5_000_000, n).astype(float)
    idx = pd.date_range(start, periods=n, freq="B", name="date")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
        index=idx,
    )


def _strat_with_context(df_levered, df_qqq):
    from stockslab.strategies.levered_etf_meanrev import LeveredEtfMeanrev
    strat = LeveredEtfMeanrev()
    strat.context = {"QQQ": df_qqq}
    return strat


class TestCausality:
    def test_generate_causal(self):
        df = _make_ohlcv(300)
        df_qqq = _make_ohlcv(300, seed=99, trend="up")
        strat = _strat_with_context(df, df_qqq)
        full = strat.generate(df)
        for k in [220, 280]:
            strat2 = _strat_with_context(df.iloc[:k], df_qqq.iloc[:k])
            part = strat2.generate(df.iloc[:k])
            pd.testing.assert_series_equal(
                full["entry_long"].iloc[:k].reset_index(drop=True),
                part["entry_long"].reset_index(drop=True),
                check_names=False,
            )


class TestEntryRules:
    def test_entry_requires_regime_and_rsi2_oversold(self):
        """entry fires only when QQQ>SMA200 AND RSI2<10 on the levered ETF."""
        n = 300
        # QQQ in strong uptrend so regime is True after warmup
        df_qqq = _make_ohlcv(n, seed=99, trend="up")
        df = _make_ohlcv(n, seed=31)
        strat = _strat_with_context(df, df_qqq)
        sigs = strat.generate(df)

        from stockslab.indicators import rsi, sma
        rsi2 = rsi(df["close"], 2)
        qqq_sma200 = sma(df_qqq["close"].reindex(df.index, method="ffill"), 200)
        qqq_close = df_qqq["close"].reindex(df.index, method="ffill")
        regime = (qqq_close > qqq_sma200) & qqq_sma200.notna()

        warm = rsi2.notna() & regime.notna()
        expected = regime & (rsi2 < 10)
        # Only check warm bars where ATR is also ready (after bar 14)
        from stockslab.indicators import atr as calc_atr
        atr14 = calc_atr(df, 14)
        warm_all = warm & atr14.notna()
        pd.testing.assert_series_equal(
            sigs["entry_long"][warm_all],
            expected[warm_all].astype(bool),
            check_names=False,
        )

    def test_no_entry_when_regime_fails(self):
        """No entry when QQQ is below its SMA200 (bear regime)."""
        n = 300
        # QQQ in downtrend
        close_qqq = 200.0 - np.linspace(0, 80, n)
        df_qqq = pd.DataFrame(
            {"open": close_qqq, "high": close_qqq + 1, "low": close_qqq - 1,
             "close": close_qqq, "volume": np.ones(n) * 1e6},
            index=pd.date_range("2015-01-01", periods=n, freq="B", name="date"),
        )
        df = _make_ohlcv(n, seed=31)
        strat = _strat_with_context(df, df_qqq)
        sigs = strat.generate(df)
        # After SMA200 is warm, regime should be False → no entries
        from stockslab.indicators import sma
        qqq_c = df_qqq["close"].reindex(df.index, method="ffill")
        qqq_sma = sma(qqq_c, 200)
        regime = (qqq_c > qqq_sma) & qqq_sma.notna()
        warm_regime = qqq_sma.notna()
        # Where regime is clearly False, no entry
        no_regime = warm_regime & ~regime
        assert not sigs["entry_long"][no_regime].any()

    def test_exit_fires_on_rsi2_above_65(self):
        df = _make_ohlcv(300)
        df_qqq = _make_ohlcv(300, seed=99, trend="up")
        strat = _strat_with_context(df, df_qqq)
        sigs = strat.generate(df)
        from stockslab.indicators import rsi
        rsi2 = rsi(df["close"], 2)
        warm = rsi2.notna()
        pd.testing.assert_series_equal(
            sigs["exit_long"][warm],
            (rsi2 > 65)[warm].astype(bool),
            check_names=False,
        )

    def test_stop_dist_is_3x_atr(self):
        df = _make_ohlcv(300)
        df_qqq = _make_ohlcv(300, seed=99, trend="up")
        strat = _strat_with_context(df, df_qqq)
        sigs = strat.generate(df)
        from stockslab.indicators import atr as calc_atr
        atr14 = calc_atr(df, 14)
        entry_mask = sigs["entry_long"]
        if entry_mask.any():
            np.testing.assert_allclose(
                sigs.loc[entry_mask, "stop_dist"].values,
                (3.0 * atr14.loc[entry_mask]).values,
                rtol=1e-10,
            )

    def test_output_columns(self):
        df = _make_ohlcv(100)
        df_qqq = _make_ohlcv(100, seed=99, trend="up")
        strat = _strat_with_context(df, df_qqq)
        out = strat.generate(df)
        assert list(out.columns) == ["entry_long", "exit_long", "stop_dist"]
        assert len(out) == len(df)
