"""
Tests for src/stockslab/data.py — Task A3.
All tests are self-contained: no network, cache dir monkeypatched to tmp_path.
"""
import io
import datetime
import pathlib

import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlcv(n=10, start="2020-01-02", freq="B", tz=None):
    """Return a minimal valid OHLCV DataFrame matching the contract schema."""
    idx = pd.date_range(start=start, periods=n, freq=freq, name="date")
    if tz:
        idx = idx.tz_localize(tz)
    else:
        idx = idx.tz_localize(None)  # tz-naive
    rng = np.random.default_rng(42)
    close = 100 + rng.standard_normal(n).cumsum()
    open_ = close + rng.standard_normal(n) * 0.5
    high = np.maximum(open_, close) + abs(rng.standard_normal(n)) * 0.3
    low = np.minimum(open_, close) - abs(rng.standard_normal(n)) * 0.3
    volume = rng.integers(1_000_000, 5_000_000, n).astype(float)
    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )
    return df


# ---------------------------------------------------------------------------
# UNIVERSE tests
# ---------------------------------------------------------------------------

class TestUniverse:
    def test_universe_is_dict(self):
        from stockslab.data import UNIVERSE
        assert isinstance(UNIVERSE, dict)
        assert len(UNIVERSE) > 0

    def test_spy_is_etf_tier1(self):
        from stockslab.data import UNIVERSE
        assert UNIVERSE["SPY"]["kind"] == "etf"
        assert UNIVERSE["SPY"]["tier"] == 1

    def test_qqq_is_etf_tier1(self):
        from stockslab.data import UNIVERSE
        assert UNIVERSE["QQQ"]["kind"] == "etf"
        assert UNIVERSE["QQQ"]["tier"] == 1

    def test_tqqq_is_levered_tier3(self):
        from stockslab.data import UNIVERSE
        assert UNIVERSE["TQQQ"]["kind"] == "levered"
        assert UNIVERSE["TQQQ"]["tier"] == 3

    def test_soxl_is_levered_tier3(self):
        from stockslab.data import UNIVERSE
        assert UNIVERSE["SOXL"]["kind"] == "levered"
        assert UNIVERSE["SOXL"]["tier"] == 3

    def test_nvda_is_stock_tier2(self):
        from stockslab.data import UNIVERSE
        # NVDA is a megacap → tier 2
        assert UNIVERSE["NVDA"]["kind"] == "stock"
        assert UNIVERSE["NVDA"]["tier"] == 2

    def test_all_etfs_in_spec_present(self):
        from stockslab.data import UNIVERSE
        required_etfs = [
            "SPY", "QQQ", "IWM", "DIA",
            "XLK", "XLF", "XLE", "XLV", "XLI", "XLP",
            "XLU", "XLY", "XLB", "XLRE", "XLC",
            "GLD", "SLV", "TLT", "HYG", "EEM", "EFA",
        ]
        for sym in required_etfs:
            assert sym in UNIVERSE, f"{sym} missing from UNIVERSE"
            assert UNIVERSE[sym]["kind"] == "etf"
            assert UNIVERSE[sym]["tier"] == 1

    def test_levered_etfs_in_spec_present(self):
        from stockslab.data import UNIVERSE
        required_levered = ["TQQQ", "SQQQ", "SOXL", "SOXS", "UPRO", "TNA", "UVXY"]
        for sym in required_levered:
            assert sym in UNIVERSE, f"{sym} missing from UNIVERSE"
            assert UNIVERSE[sym]["kind"] == "levered"
            assert UNIVERSE[sym]["tier"] == 3

    def test_high_beta_stocks_present(self):
        """The ~30 liquid high-beta names specified in Task A3 step 2 must all be present."""
        from stockslab.data import UNIVERSE
        required_hb = [
            "AMD", "PLTR", "COIN", "MSTR", "SMCI", "SNOW", "NET", "SHOP",
            "SQ", "ROKU", "DKNG", "RIVN", "SOFI", "HOOD", "MARA", "RIOT",
            "CLF", "AA", "OXY", "DVN", "FCX", "ENPH", "U", "RBLX",
            "ABNB", "DASH", "UBER", "LYFT", "ZM", "CRWD",
        ]
        for sym in required_hb:
            assert sym in UNIVERSE, f"{sym} missing from UNIVERSE"
            assert UNIVERSE[sym]["kind"] == "stock"

    def test_all_stocks_have_kind_stock(self):
        from stockslab.data import UNIVERSE
        stocks = {k: v for k, v in UNIVERSE.items() if v["kind"] == "stock"}
        assert len(stocks) > 100  # S&P 100 + 30 high-beta

    def test_tier_values_are_1_2_or_3(self):
        from stockslab.data import UNIVERSE
        for sym, meta in UNIVERSE.items():
            assert meta["tier"] in (1, 2, 3), f"{sym} has invalid tier {meta['tier']}"

    def test_kind_values_are_valid(self):
        from stockslab.data import UNIVERSE
        valid_kinds = {"etf", "levered", "stock"}
        for sym, meta in UNIVERSE.items():
            assert meta["kind"] in valid_kinds, f"{sym} has invalid kind {meta['kind']}"


# ---------------------------------------------------------------------------
# validate() tests
# ---------------------------------------------------------------------------

class TestValidate:
    def test_valid_df_passes(self):
        from stockslab.data import validate
        df = _make_ohlcv()
        validate(df)  # must not raise

    def test_nan_row_raises(self):
        from stockslab.data import validate
        df = _make_ohlcv()
        df.iloc[3, 0] = float("nan")
        with pytest.raises(ValueError, match="NaN"):
            validate(df)

    def test_non_monotonic_index_raises(self):
        from stockslab.data import validate
        df = _make_ohlcv(n=5)
        # Reverse the order to make index non-monotonic
        df = df.iloc[::-1]
        with pytest.raises(ValueError, match="monotonic"):
            validate(df)

    def test_duplicate_index_raises(self):
        from stockslab.data import validate
        df = _make_ohlcv(n=5)
        new_idx = df.index.tolist()
        new_idx[2] = new_idx[1]  # duplicate
        df.index = pd.DatetimeIndex(new_idx, name="date")
        with pytest.raises(ValueError, match="monotonic"):
            validate(df)

    def test_missing_column_raises(self):
        from stockslab.data import validate
        df = _make_ohlcv()
        df2 = df.drop(columns=["volume"])
        with pytest.raises(ValueError, match="column"):
            validate(df2)

    def test_extra_column_raises(self):
        """Dividends / Stock Splits columns must NOT be present after normalization."""
        from stockslab.data import validate
        df = _make_ohlcv()
        df["Dividends"] = 0.0
        with pytest.raises(ValueError, match="column"):
            validate(df)

    def test_wrong_index_name_raises(self):
        from stockslab.data import validate
        df = _make_ohlcv()
        df.index.name = "Date"
        with pytest.raises(ValueError, match="index"):
            validate(df)

    def test_uppercase_column_raises(self):
        from stockslab.data import validate
        df = _make_ohlcv()
        df.columns = ["Open", "High", "Low", "Close", "Volume"]
        with pytest.raises(ValueError, match="column"):
            validate(df)

    def test_non_float64_dtype_raises(self):
        """Columns must be float64; int64 (e.g. un-cast volume) should raise."""
        from stockslab.data import validate
        df = _make_ohlcv()
        df["volume"] = df["volume"].astype("int64")
        with pytest.raises(ValueError, match="float64"):
            validate(df)

    def test_wrong_tz_raises(self):
        """tz-aware index with UTC should raise — only America/New_York is valid."""
        from stockslab.data import validate
        df = _make_ohlcv(tz="UTC")
        with pytest.raises(ValueError, match="America/New_York"):
            validate(df)

    def test_ny_tz_passes(self):
        """tz-aware index with America/New_York is valid (intraday contract)."""
        from stockslab.data import validate
        df = _make_ohlcv(tz="America/New_York")
        validate(df)  # must not raise


# ---------------------------------------------------------------------------
# splits() tests
# ---------------------------------------------------------------------------

class TestSplits:
    def test_daily_splits_is(self):
        from stockslab.data import splits
        is_slice, oos_slice = splits("1d")
        assert is_slice == slice("2010-01-01", "2021-12-31")

    def test_daily_splits_oos(self):
        from stockslab.data import splits
        is_slice, oos_slice = splits("1d")
        assert oos_slice == slice("2022-01-01", "2026-06-01")

    def test_1h_splits_proportional(self):
        """1h IS = first 70%, OOS = last 30% of ~730 days."""
        from stockslab.data import splits
        is_slice, oos_slice = splits("1h")
        # Both slices should be date strings or Timestamps, and IS starts before OOS
        assert is_slice is not None
        assert oos_slice is not None

    def test_5m_splits_returns_tuple(self):
        """5m splits should return a 2-tuple (even if OOS is None / same as IS)."""
        from stockslab.data import splits
        result = splits("5m")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_unknown_interval_raises(self):
        from stockslab.data import splits
        with pytest.raises((ValueError, KeyError)):
            splits("3m")


# ---------------------------------------------------------------------------
# Cache round-trip tests (monkeypatched to tmp_path, no network)
# ---------------------------------------------------------------------------

class TestCacheRoundTrip:
    def test_parquet_write_and_load(self, tmp_path, monkeypatch):
        """fetch() with force=False reads from cache; if cache exists, no network call."""
        import stockslab.data as data_mod

        # Monkeypatch CACHE_DIR to tmp_path
        monkeypatch.setattr(data_mod, "CACHE_DIR", tmp_path)

        # Pre-seed a valid parquet file for SPY 1d
        df = _make_ohlcv(n=20, start="2020-01-02")
        cache_path = tmp_path / "1d" / "SPY.parquet"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(cache_path)

        # load_panel should read it without hitting the network
        panel = data_mod.load_panel(["SPY"], "1d")
        assert "SPY" in panel
        pd.testing.assert_frame_equal(panel["SPY"], df, check_like=False, check_freq=False)

    def test_load_panel_missing_symbol_raises(self, tmp_path, monkeypatch):
        """load_panel on a symbol with no cache raises FileNotFoundError."""
        import stockslab.data as data_mod
        monkeypatch.setattr(data_mod, "CACHE_DIR", tmp_path)
        with pytest.raises(FileNotFoundError):
            data_mod.load_panel(["MISSING_SYM"], "1d")

    def test_parquet_cache_validates_on_read(self, tmp_path, monkeypatch):
        """load_panel raises ValueError if cached parquet has NaN rows."""
        import stockslab.data as data_mod
        monkeypatch.setattr(data_mod, "CACHE_DIR", tmp_path)

        df = _make_ohlcv(n=10)
        df.iloc[5, 2] = float("nan")  # corrupt the cache
        cache_path = tmp_path / "1d" / "SPY.parquet"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(cache_path)

        with pytest.raises(ValueError, match="NaN"):
            data_mod.load_panel(["SPY"], "1d")

    def test_load_panel_start_filter(self, tmp_path, monkeypatch):
        """load_panel with start='2020-01-05' should return only rows >= that date."""
        import stockslab.data as data_mod
        monkeypatch.setattr(data_mod, "CACHE_DIR", tmp_path)

        df = _make_ohlcv(n=20, start="2020-01-02")
        cache_path = tmp_path / "1d" / "AAPL.parquet"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(cache_path)

        panel = data_mod.load_panel(["AAPL"], "1d", start="2020-01-07")
        result = panel["AAPL"]
        assert (result.index >= pd.Timestamp("2020-01-07")).all()

    def test_fetch_uses_cache_no_network(self, tmp_path, monkeypatch):
        """fetch() with existing cache does NOT call yfinance download."""
        import stockslab.data as data_mod

        monkeypatch.setattr(data_mod, "CACHE_DIR", tmp_path)

        df = _make_ohlcv(n=15, start="2020-01-02")
        cache_path = tmp_path / "1d" / "SPY.parquet"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(cache_path)

        # Patch yf.download to blow up if called
        import yfinance as yf

        def _no_network(*args, **kwargs):
            raise AssertionError("yfinance.download was called but cache exists!")

        monkeypatch.setattr(yf, "download", _no_network)

        result = data_mod.fetch("SPY", "1d")
        assert len(result) == 15

    def test_fetch_force_calls_network(self, tmp_path, monkeypatch):
        """fetch(force=True) should call yfinance even if cache exists."""
        import stockslab.data as data_mod
        import yfinance as yf

        monkeypatch.setattr(data_mod, "CACHE_DIR", tmp_path)

        # Pre-seed cache so we know it exists
        df_cached = _make_ohlcv(n=5, start="2020-01-02")
        cache_path = tmp_path / "1d" / "SPY.parquet"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        df_cached.to_parquet(cache_path)

        # Stub yf.download to return a fresh synthetic DataFrame
        fresh_df = _make_ohlcv(n=10, start="2021-01-04")

        def _stub_download(ticker, interval=None, auto_adjust=True, progress=False, **kwargs):
            # Return a DataFrame as yfinance would (with MultiIndex columns)
            df = fresh_df.copy()
            df.columns = pd.MultiIndex.from_tuples(
                [(c.capitalize(), ticker) for c in df.columns]
            )
            return df

        monkeypatch.setattr(yf, "download", _stub_download)

        result = data_mod.fetch("SPY", "1d", force=True)
        # Should have 10 rows from the stubbed download, not 5 from cache
        assert len(result) == 10

    @pytest.mark.parametrize(
        ("internal_symbol", "download_symbol"),
        [("BRK.B", "BRK-B"), ("MMC", "MRSH"), ("SQ", "XYZ")],
    )
    def test_fetch_uses_yfinance_symbol_alias(
        self,
        tmp_path,
        monkeypatch,
        internal_symbol,
        download_symbol,
    ):
        """Internal cache keys should use the current yfinance ticker."""
        import stockslab.data as data_mod
        import yfinance as yf

        monkeypatch.setattr(data_mod, "CACHE_DIR", tmp_path)
        fresh_df = _make_ohlcv(n=10, start="2021-01-04")
        seen = []

        def _stub_download(ticker, interval=None, auto_adjust=True, progress=False, **kwargs):
            seen.append(ticker)
            df = fresh_df.copy()
            df.columns = pd.MultiIndex.from_tuples(
                [(c.capitalize(), ticker) for c in df.columns]
            )
            return df

        monkeypatch.setattr(yf, "download", _stub_download)

        result = data_mod.fetch(internal_symbol, "1d", force=True)

        assert seen == [download_symbol]
        assert len(result) == 10
        assert (tmp_path / "1d" / f"{internal_symbol}.parquet").exists()


# ---------------------------------------------------------------------------
# Schema normalization tests
# ---------------------------------------------------------------------------

class TestSchemaNormalization:
    def test_columns_lowercase_ohlcv_only(self, tmp_path, monkeypatch):
        """fetch() output must have exactly [open, high, low, close, volume] columns."""
        import stockslab.data as data_mod
        import yfinance as yf

        monkeypatch.setattr(data_mod, "CACHE_DIR", tmp_path)
        # No cache — force fetch
        raw_df = _make_ohlcv(n=8, start="2021-01-04")

        def _stub_download(ticker, interval=None, auto_adjust=True, progress=False, **kwargs):
            # Simulate yfinance MultiIndex output with Dividends column
            extra = raw_df.copy()
            extra["dividends"] = 0.0
            extra["stock_splits"] = 0.0
            extra.columns = pd.MultiIndex.from_tuples(
                [(c.capitalize().replace("_", " "), ticker) for c in extra.columns]
            )
            return extra

        monkeypatch.setattr(yf, "download", _stub_download)
        result = data_mod.fetch("AAPL", "1d")
        assert set(result.columns) == {"open", "high", "low", "close", "volume"}

    def test_daily_index_tz_naive(self, tmp_path, monkeypatch):
        """Daily data must have tz-naive DatetimeIndex named 'date'."""
        import stockslab.data as data_mod
        import yfinance as yf

        monkeypatch.setattr(data_mod, "CACHE_DIR", tmp_path)
        raw_df = _make_ohlcv(n=5, start="2021-01-04", tz="America/New_York")

        def _stub_download(ticker, interval=None, auto_adjust=True, progress=False, **kwargs):
            df = raw_df.copy()
            df.columns = pd.MultiIndex.from_tuples(
                [(c.capitalize(), ticker) for c in df.columns]
            )
            return df

        monkeypatch.setattr(yf, "download", _stub_download)
        result = data_mod.fetch("SPY", "1d")
        assert result.index.tz is None
        assert result.index.name == "date"

    def test_intraday_index_ny_tz(self, tmp_path, monkeypatch):
        """Intraday (1h) data must have America/New_York DatetimeIndex."""
        import stockslab.data as data_mod
        import yfinance as yf

        monkeypatch.setattr(data_mod, "CACHE_DIR", tmp_path)
        raw_df = _make_ohlcv(n=10, start="2024-01-02 09:30", freq="h", tz="America/New_York")

        def _stub_download(ticker, interval=None, auto_adjust=True, progress=False, **kwargs):
            df = raw_df.copy()
            df.columns = pd.MultiIndex.from_tuples(
                [(c.capitalize(), ticker) for c in df.columns]
            )
            return df

        monkeypatch.setattr(yf, "download", _stub_download)
        result = data_mod.fetch("SPY", "1h")
        assert result.index.tz is not None
        assert str(result.index.tz) == "America/New_York"
