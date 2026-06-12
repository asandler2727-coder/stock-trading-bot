"""Tests for the Opening Range Breakout (ORB) strategy."""
import numpy as np
import pandas as pd
import pytz


def _make_intraday_ohlcv(n_days=5, bars_per_day=7, seed=53):
    """Create synthetic intraday OHLCV data with tz-aware America/New_York index."""
    rng = np.random.default_rng(seed)
    ny = pytz.timezone("America/New_York")
    rows = []
    for day in range(n_days):
        base_date = pd.Timestamp("2024-01-02") + pd.Timedelta(days=day)
        if base_date.weekday() >= 5:
            continue
        for bar in range(bars_per_day):
            ts = base_date.replace(hour=9 + bar, minute=30, tzinfo=ny)
            close = 100.0 + rng.standard_normal()
            open_ = close + rng.standard_normal() * 0.1
            high = max(open_, close) + abs(rng.standard_normal()) * 0.2
            low = min(open_, close) - abs(rng.standard_normal()) * 0.2
            rows.append({"date": ts, "open": open_, "high": high, "low": low,
                          "close": close, "volume": 1e6})
    df = pd.DataFrame(rows).set_index("date")
    df.index.name = "date"
    return df


def _make_clean_session(n_days=10, bars_per_day=7):
    """Two-session synthetic data for scenario tests."""
    ny = pytz.timezone("America/New_York")
    rows = []
    rng = np.random.default_rng(77)
    for day in range(n_days):
        base_date = pd.Timestamp("2024-01-02") + pd.Timedelta(days=day)
        if base_date.weekday() >= 5:
            continue
        close_base = 100.0
        for bar in range(bars_per_day):
            ts = base_date.replace(hour=9 + bar, minute=30, tzinfo=ny)
            c = close_base + rng.standard_normal() * 0.2
            o = c + rng.standard_normal() * 0.1
            h = max(o, c) + abs(rng.standard_normal()) * 0.15
            l = min(o, c) - abs(rng.standard_normal()) * 0.15
            rows.append({"date": ts, "open": o, "high": h, "low": l,
                          "close": c, "volume": 1e6})
    df = pd.DataFrame(rows).set_index("date")
    df.index.name = "date"
    return df


def _strat():
    from stockslab.strategies.orb import Orb
    return Orb()


class TestCausality:
    def test_generate_causal(self):
        df = _make_intraday_ohlcv(n_days=20, bars_per_day=7)
        strat = _strat()
        full = strat.generate(df)
        for k in [20, 50, len(df) - 1]:
            if k >= len(df):
                k = len(df) - 1
            part = strat.generate(df.iloc[:k])
            pd.testing.assert_series_equal(
                full["entry_long"].iloc[:k].reset_index(drop=True),
                part["entry_long"].reset_index(drop=True),
                check_names=False,
            )


class TestEntryRules:
    def test_no_entry_on_first_bar_of_session(self):
        """The opening range is defined by the first bar; that bar never triggers entry."""
        df = _make_intraday_ohlcv(n_days=10, bars_per_day=7)
        strat = _strat()
        sigs = strat.generate(df)
        dates = df.index.normalize()
        dates_s = pd.Series(dates.asi8, index=df.index)
        is_first = (dates_s != dates_s.shift(1)).fillna(True)
        assert not sigs["entry_long"][is_first].any()

    def test_entry_fires_when_close_exceeds_session_high(self):
        """Force one bar's close well above session high — entry must fire."""
        ny = pytz.timezone("America/New_York")
        # Session: first bar sets high=101; second bar closes at 105 (breakout)
        base = pd.Timestamp("2024-01-02")
        rows = [
            {"date": base.replace(hour=9, minute=30, tzinfo=ny),
             "open": 99.0, "high": 101.0, "low": 98.0, "close": 100.0, "volume": 1e6},
            {"date": base.replace(hour=10, minute=30, tzinfo=ny),
             "open": 101.5, "high": 106.0, "low": 101.0, "close": 105.0, "volume": 1e6},
            {"date": base.replace(hour=11, minute=30, tzinfo=ny),
             "open": 104.0, "high": 106.0, "low": 103.0, "close": 104.0, "volume": 1e6},
        ]
        df = pd.DataFrame(rows).set_index("date")
        df.index.name = "date"
        strat = _strat()
        sigs = strat.generate(df)
        assert sigs["entry_long"].iloc[1], "bar 1 close(105) > session_high(101) → must fire"
        assert not sigs["entry_long"].iloc[0], "first bar must not fire"

    def test_session_exit_flag(self):
        strat = _strat()
        assert strat.session_exit is True

    def test_target_r_is_2(self):
        strat = _strat()
        assert strat.target_r == 2.0

    def test_output_columns(self):
        df = _make_intraday_ohlcv(n_days=3)
        strat = _strat()
        out = strat.generate(df)
        assert list(out.columns) == ["entry_long", "exit_long", "stop_dist"]
        assert len(out) == len(df)
