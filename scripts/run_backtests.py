import argparse
import json
import logging
from pathlib import Path
import time
import subprocess
import pandas as pd
from stockslab.strategies import load_all
from stockslab import data, engine, metrics, result_contract
from stockslab.strategies.base import SignalStrategy, RotationStrategy

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategies", nargs="*", help="Run specific strategies or all if not provided")
    parser.add_argument("--split", choices=["IS", "OOS", "full"], required=True)
    parser.add_argument("--slippage-mult", type=float, default=1.0)
    args = parser.parse_args()

    Path("results").mkdir(exist_ok=True)

    registry = load_all()
    strats = args.strategies if args.strategies else list(registry.keys())

    for strat_name in strats:
        if strat_name not in registry:
            print(f"Strategy {strat_name} not found.")
            continue
        
        strat = registry[strat_name]
        
        if strat.universe == "all":
            syms = list(data.UNIVERSE.keys())
        else:
            kind_map = {"stocks": "stock", "etfs": "etf", "levered": "levered"}
            target_kind = kind_map.get(strat.universe, "stock")
            syms = [s for s, info in data.UNIVERSE.items() if info["kind"] == target_kind]

        if strat_name == "levered_etf_meanrev" and "QQQ" not in syms:
            syms.append("QQQ")
        if isinstance(strat, RotationStrategy) and "SPY" not in syms:
            syms.append("SPY")

        # Only load symbols that actually exist in the cache
        valid_syms = []
        for s in syms:
            if Path(f"data/{strat.timeframe}/{s}.parquet").exists():
                valid_syms.append(s)
        syms = valid_syms

        try:
            panel = data.load_panel(syms, strat.timeframe)
        except Exception as e:
            print(f"Skipping {strat_name}: error loading panel: {e}")
            continue

        is_slice, oos_slice = data.splits(strat.timeframe)
        if args.split == "IS":
            target_slice = is_slice
        elif args.split == "OOS":
            target_slice = oos_slice
        else:
            target_slice = slice(is_slice.start, oos_slice.stop)

        sliced_panel = {s: df.loc[target_slice] for s, df in panel.items() if len(df.loc[target_slice]) > 0}
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

        if not trades:
            print(f"[{strat_name}] No trades generated.")
            continue
            
        summary = metrics.summarize(trades)
        
        passed, reasons = metrics.phase1_gate(summary)
        print(f"[{strat_name}] Split: {args.split} | PF: {summary['pf']:.2f} | N: {summary['n']} | Gate Passed: {passed}")
        
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode("utf-8").strip()
        run_id = f"{strat_name}_{args.split}_{commit[:8]}_{int(time.time())}"
        
        run_metadata = {
            "run_id": run_id,
            "repo_commit": commit,
            "interval": strat.timeframe,
            "split_label": args.split
        }
        
        contract_res = result_contract.build_backtest_result(strat, sliced_panel, trades, run_metadata)
        
        out_json = Path("results") / f"{run_id}.json"
        with open(out_json, "w") as f:
            json.dump(contract_res, f, indent=2)
            
        out_csv = Path("results") / f"{strat_name}_{args.split}_trades.csv"
        if contract_res.get("trades"):
            pd.DataFrame(contract_res["trades"]).to_csv(out_csv, index=False)

if __name__ == "__main__":
    main()
