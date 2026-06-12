"""Tests for VWAP Reclaim strategy."""
import numpy as np
import pandas as pd
import pytz

def _make_intraday_ohlcv(n_days=5, bars_per_day=7, seed=53):
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

def _strat():
    from stockslab.strategies.vwap_reclaim import VwapReclaim
    return VwapReclaim()

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
    def test_entry_fires_correctly(self):
        ny = pytz.timezone("America/New_York")
        base = pd.Timestamp("2024-01-02")
        rows = [
            # Bar 0: open > close (red bar)
            {"date": base.replace(hour=9, minute=30, tzinfo=ny),
             "open": 100.0, "high": 101.0, "low": 98.0, "close": 99.0, "volume": 1000},
            # Bar 1: high < vwap (fully below)
            {"date": base.replace(hour=10, minute=30, tzinfo=ny),
             "open": 98.0, "high": 98.5, "low": 97.0, "close": 98.0, "volume": 1000},
            # Bar 2: close > vwap
            {"date": base.replace(hour=11, minute=30, tzinfo=ny),
             "open": 98.0, "high": 102.0, "low": 98.0, "close": 101.0, "volume": 1000},
        ]
        df = pd.DataFrame(rows).set_index("date")
        df.index.name = "date"
        strat = _strat()
        sigs = strat.generate(df)
        
        assert sigs["entry_long"].iloc[2], "Must enter when reclaiming VWAP after fully below"
        assert not sigs["entry_long"].iloc[0]
        assert not sigs["entry_long"].iloc[1]
