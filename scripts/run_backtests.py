import argparse
import json
import math
from pathlib import Path
import time
import subprocess
import pandas as pd
from stockslab.strategies import load_all
from stockslab import data, engine, metrics, result_contract
from stockslab.strategies.base import SignalStrategy, RotationStrategy

def resolve_symbols(strat):
    if strat.universe == "all":
        syms = [s for s, info in data.UNIVERSE.items() if info["kind"] != "levered"]
    else:
        kind_map = {"stocks": "stock", "etfs": "etf", "levered": "levered"}
        target_kind = kind_map.get(strat.universe, "stock")
        syms = [s for s, info in data.UNIVERSE.items() if info["kind"] == target_kind]

    if strat.name == "levered_etf_meanrev" and "QQQ" not in syms:
        syms.append("QQQ")
    if isinstance(strat, RotationStrategy) and "SPY" not in syms:
        syms.append("SPY")
    return syms


def require_cached_symbols(syms, timeframe, allow_missing_cache=False):
    missing = [s for s in syms if not Path(f"data/{timeframe}/{s}.parquet").exists()]
    if missing and not allow_missing_cache:
        raise FileNotFoundError(
            f"Missing cached parquet for {len(missing)} symbol(s) at data/{timeframe}: "
            f"{', '.join(missing)}. Run scripts/fetch_data.py or rerun with "
            "--allow-missing-cache for a diagnostic partial-universe run."
        )
    if missing:
        print(f"WARNING: omitting {len(missing)} missing cached symbol(s): {', '.join(missing)}")
    return [s for s in syms if s not in set(missing)], missing


def execution_slice_for_split(split_label, timeframe):
    is_slice, oos_slice = data.splits(timeframe)
    if split_label == "IS":
        return is_slice, is_slice
    if split_label == "OOS":
        # Include the IS history so long indicators are warm at OOS start, then
        # filter completed trades to OOS entries below.
        return slice(is_slice.start, oos_slice.stop), oos_slice
    return slice(is_slice.start, oos_slice.stop), slice(is_slice.start, oos_slice.stop)


def slice_panel(panel, target_slice):
    return {s: df.loc[target_slice] for s, df in panel.items() if len(df.loc[target_slice]) > 0}


def trade_in_slice(trade, target_slice):
    entry = pd.Timestamp(trade.entry_date)
    start = pd.Timestamp(target_slice.start) if target_slice.start else None
    stop = pd.Timestamp(target_slice.stop) if target_slice.stop else None
    if start is not None and entry < start:
        return False
    if stop is not None and entry > stop:
        return False
    return True


def write_legacy_summary(strat_name, split_label, summary):
    out_json = Path("results") / f"{strat_name}_{split_label}.json"
    clean = {}
    for key, value in summary.items():
        if isinstance(value, float) and math.isinf(value):
            clean[key] = value
        else:
            clean[key] = value
    with open(out_json, "w") as f:
        json.dump(clean, f, indent=2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategies", nargs="*", help="Run specific strategies or all if not provided")
    parser.add_argument("--split", choices=["IS", "OOS", "full"], required=True)
    parser.add_argument("--slippage-mult", type=float, default=1.0)
    parser.add_argument(
        "--allow-missing-cache",
        action="store_true",
        help="Continue after printing missing cached symbols. Intended only for diagnostics.",
    )
    args = parser.parse_args()

    Path("results").mkdir(exist_ok=True)

    registry = load_all()
    strats = args.strategies if args.strategies else list(registry.keys())

    for strat_name in strats:
        if strat_name not in registry:
            print(f"Strategy {strat_name} not found.")
            continue
        
        strat = registry[strat_name]
        requested_syms = resolve_symbols(strat)
        try:
            syms, missing_syms = require_cached_symbols(
                requested_syms,
                strat.timeframe,
                allow_missing_cache=args.allow_missing_cache,
            )
        except FileNotFoundError as e:
            raise SystemExit(str(e)) from e

        try:
            panel = data.load_panel(syms, strat.timeframe)
        except Exception as e:
            print(f"Skipping {strat_name}: error loading panel: {e}")
            continue

        execution_slice, evaluation_slice = execution_slice_for_split(args.split, strat.timeframe)
        sliced_panel = slice_panel(panel, execution_slice)
        tiers = {s: data.UNIVERSE[s]["tier"] for s in sliced_panel}

        if isinstance(strat, RotationStrategy):
            bps_map = {s: engine.TIER_BPS[tiers[s]] * args.slippage_mult for s in sliced_panel}
            trades = engine.run_rotation_backtest(strat, sliced_panel, bps_map)
        else:
            orig_tier_bps = engine.TIER_BPS.copy()
            engine.TIER_BPS = {k: v * args.slippage_mult for k, v in orig_tier_bps.items()}
            try:
                trades = engine.run_universe(strat, sliced_panel, tiers)
            finally:
                engine.TIER_BPS = orig_tier_bps

        trades = [t for t in trades if trade_in_slice(t, evaluation_slice)]
        if not trades:
            print(f"[{strat_name}] No trades generated.")
            continue
            
        summary = metrics.summarize(trades)
        
        if args.split == "OOS":
            passed, reasons = metrics.phase2_oos(summary)
        else:
            passed, reasons = metrics.phase1_gate(summary)
        print(f"[{strat_name}] Split: {args.split} | PF: {summary['pf']:.2f} | N: {summary['n']} | Gate Passed: {passed}")
        
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode("utf-8").strip()
        run_id = f"{strat_name}_{args.split}_{commit[:8]}_{int(time.time())}"
        
        run_metadata = {
            "run_id": run_id,
            "repo_commit": commit,
            "interval": strat.timeframe,
            "split_label": args.split,
            "evaluation_start": evaluation_slice.start,
            "evaluation_end": evaluation_slice.stop,
            "warmup_start": execution_slice.start,
            "slippage_mult": args.slippage_mult,
            "requested_symbols": requested_syms,
            "missing_symbols": missing_syms,
        }
        
        contract_res = result_contract.build_backtest_result(strat, sliced_panel, trades, run_metadata)
        
        out_json = Path("results") / f"{run_id}.json"
        with open(out_json, "w") as f:
            json.dump(contract_res, f, indent=2)

        write_legacy_summary(strat_name, args.split, summary)
            
        out_csv = Path("results") / f"{strat_name}_{args.split}_trades.csv"
        if contract_res.get("trades"):
            pd.DataFrame(contract_res["trades"]).to_csv(out_csv, index=False)

if __name__ == "__main__":
    main()
