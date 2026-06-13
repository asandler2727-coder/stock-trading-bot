from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from stockslab.engine import Trade


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_backtests.py"
SPEC = importlib.util.spec_from_file_location("run_backtests_script", SCRIPT_PATH)
run_backtests = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(run_backtests)


def _trade(entry_date: str) -> Trade:
    return Trade(
        symbol="AAPL",
        entry_date=pd.Timestamp(entry_date),
        exit_date=pd.Timestamp(entry_date) + pd.Timedelta(days=1),
        entry=100.0,
        exit=101.0,
        shares=1.0,
        r_multiple=1.0,
        pct_return=0.01,
        exit_reason="signal",
    )


def test_missing_cache_fails_loud_by_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError, match="Missing cached parquet"):
        run_backtests.require_cached_symbols(["AAPL"], "1d")


def test_missing_cache_can_be_allowed_for_diagnostics(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "1d").mkdir(parents=True)
    (tmp_path / "data" / "1d" / "AAPL.parquet").touch()

    syms, missing = run_backtests.require_cached_symbols(
        ["AAPL", "MSFT"],
        "1d",
        allow_missing_cache=True,
    )

    assert syms == ["AAPL"]
    assert missing == ["MSFT"]


def test_all_universe_excludes_levered_etfs():
    class DummyStrategy:
        universe = "all"
        name = "dummy"

    syms = run_backtests.resolve_symbols(DummyStrategy())

    assert "SPY" in syms
    assert "AAPL" in syms
    assert "TQQQ" not in syms
    assert "SQQQ" not in syms
    assert "UVXY" not in syms


def test_oos_uses_warm_execution_slice_and_oos_evaluation_slice():
    execution_slice, evaluation_slice = run_backtests.execution_slice_for_split("OOS", "1d")

    assert execution_slice.start == "2010-01-01"
    assert execution_slice.stop == "2026-06-01"
    assert evaluation_slice.start == "2022-01-01"
    assert evaluation_slice.stop == "2026-06-01"


def test_trade_filter_keeps_only_entries_inside_evaluation_slice():
    evaluation_slice = slice("2022-01-01", "2026-06-01")

    assert not run_backtests.trade_in_slice(_trade("2021-12-31"), evaluation_slice)
    assert run_backtests.trade_in_slice(_trade("2022-01-01"), evaluation_slice)
    assert run_backtests.trade_in_slice(_trade("2026-06-01"), evaluation_slice)
    assert not run_backtests.trade_in_slice(_trade("2026-06-02"), evaluation_slice)
