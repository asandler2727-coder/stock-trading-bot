import json
import pathlib
import copy
import pytest
from jsonschema import Draft202012Validator
from stockslab import result_contract, engine
from stockslab.strategies.base import SignalStrategy
import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
CONTRACTS_DIR = HERE.parent / "contracts"
SCHEMA_PATH = CONTRACTS_DIR / "result_contract.schema.json"

@pytest.fixture(scope="session")
def schema():
    with SCHEMA_PATH.open() as fh:
        return json.load(fh)

@pytest.fixture(scope="session")
def validator(schema):
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)

def test_schema_valid(schema):
    Draft202012Validator.check_schema(schema)

def test_examples_conform(validator):
    examples_dir = CONTRACTS_DIR / "examples"
    examples = list(examples_dir.glob("*.json"))
    assert len(examples) > 0, "No examples found"
    for path in examples:
        with path.open() as fh:
            instance = json.load(fh)
        errors = list(validator.iter_errors(instance))
        assert not errors, f"Validation failed for {path.name}: {errors}"

def test_guards_bite(validator):
    examples_dir = CONTRACTS_DIR / "examples"
    examples = list(examples_dir.glob("*.json"))
    with examples[0].open() as fh:
        instance = json.load(fh)

    # 1. Boundary
    m = dict(instance)
    m["max_daily_loss"] = 500
    assert list(validator.iter_errors(m))

    # 2. Naive ts
    if instance.get("signals"):
        m = copy.deepcopy(instance)
        m["signals"][0]["data_available_at"] = "2024-03-05T11:30:00"
        assert list(validator.iter_errors(m))

    # 3. Live inputs
    if instance.get("signals"):
        m = copy.deepcopy(instance)
        m["strategy"]["live_capable"] = True
        m["signals"][0]["required_inputs"] = None
        assert list(validator.iter_errors(m))

    # 4. Backtest stats
    m = copy.deepcopy(instance)
    m["payload_type"] = "backtest_result"
    m.pop("empirical_risk_stats", None)
    assert list(validator.iter_errors(m))

    # 5. Live refs
    m = copy.deepcopy(instance)
    m["payload_type"] = "live_signals"
    m.pop("validation_refs", None)
    assert list(validator.iter_errors(m))

def test_round_trip_synthetic(validator):
    class MockStrategy(SignalStrategy):
        name = "mock_strat"
        version = "1.0"
        timeframe = "1d"
        universe = "test"
        live_capable = False
        params = {}
        entry_at_open = False
        target_r = 1.5
        trail_atr_mult = None
        time_stop_bars = None
        session_exit = False
        def generate(self, df):
            sigs = pd.DataFrame(index=df.index)
            sigs["entry_long"] = False
            sigs["exit_long"] = False
            sigs["stop_dist"] = 1.0
            
            # Entry on second bar
            sigs.loc[df.index[1], "entry_long"] = True
            # Exit on fourth bar
            sigs.loc[df.index[3], "exit_long"] = True
            return sigs

    dates = pd.date_range("2024-01-01", periods=5, freq="D")
    dates = pd.DatetimeIndex([d.replace(tzinfo=None) for d in dates])
    
    df = pd.DataFrame({
        "open": [10, 11, 12, 13, 14],
        "high": [11, 12, 13, 14, 15],
        "low": [9, 10, 11, 12, 13],
        "close": [10.5, 11.5, 12.5, 13.5, 14.5],
        "volume": [100]*5
    }, index=dates)
    
    strat = MockStrategy()
    panel = {"TEST": df}
    trades = engine.run_signal_backtest(strat, df, "TEST", 1)
    
    metadata = {
        "run_id": "test_run",
        "repo_commit": "abcdef0",
        "interval": "1d",
        "split_label": "IS"
    }
    
    res = result_contract.build_backtest_result(strat, panel, trades, metadata)
    
    errors = list(validator.iter_errors(res))
    assert not errors, f"Roundtrip result validation failed: {errors}"
    
    for sig in res["signals"]:
        da = pd.Timestamp(sig["data_available_at"])
        dvf = pd.Timestamp(sig["decision_valid_from"])
        assert da <= dvf, f"Lookahead invariant violated: {da} > {dvf}"
        
    if res.get("trades"):
        signal_ids = {s["signal_id"] for s in res["signals"]}
        for t in res["trades"]:
            sid = t["source_signal_id"]
            assert sid is not None
            assert sid in signal_ids
