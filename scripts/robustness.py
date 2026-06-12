import json
from pathlib import Path
from stockslab.strategies import load_all
from stockslab import data, engine, metrics
from stockslab.strategies.base import RotationStrategy
import copy

def run_strat(strat, slippage_mult=1.0):
    if strat.universe == "all":
        syms = list(data.UNIVERSE.keys())
    else:
        kind_map = {"stocks": "stock", "etfs": "etf", "levered": "levered"}
        target_kind = kind_map.get(strat.universe, "stock")
        syms = [s for s, info in data.UNIVERSE.items() if info["kind"] == target_kind]

    if strat.name == "levered_etf_meanrev" and "QQQ" not in syms:
        syms.append("QQQ")
    if isinstance(strat, RotationStrategy) and "SPY" not in syms:
        syms.append("SPY")

    try:
        panel = data.load_panel(syms, strat.timeframe)
    except Exception as e:
        print(f"Skipping {strat.name}: error loading panel: {e}")
        return None

    is_slice, _ = data.splits(strat.timeframe)
    sliced_panel = {s: df.loc[is_slice] for s, df in panel.items() if len(df.loc[is_slice]) > 0}
    tiers = {s: data.UNIVERSE[s]["tier"] for s in sliced_panel}

    if isinstance(strat, RotationStrategy):
        bps_map = {s: engine.TIER_BPS[tiers[s]] * slippage_mult for s in sliced_panel}
        trades = engine.run_rotation_backtest(strat, sliced_panel, bps_map)
    else:
        orig_tier_bps = engine.TIER_BPS.copy()
        engine.TIER_BPS = {k: v * slippage_mult for k, v in orig_tier_bps.items()}
        try:
            trades = engine.run_universe(strat, sliced_panel, tiers)
        finally:
            engine.TIER_BPS = orig_tier_bps
            
    if not trades:
        return None
    return metrics.summarize(trades)

def main():
    registry = load_all()
    Path("results").mkdir(exist_ok=True)
    
    survivors = []
    for p in Path("results").glob("*_IS.json"):
        strat_name = p.stem.replace("_IS", "")
        with open(p) as f:
            summary = json.load(f)
        passed, _ = metrics.phase1_gate(summary)
        if passed and strat_name in registry:
            survivors.append(strat_name)

    print(f"Found {len(survivors)} IS gate survivors.")
    for strat_name in survivors:
        print(f"Running robustness for {strat_name}...")
        strat = registry[strat_name]
        results_list = []
        
        summ = run_strat(strat, slippage_mult=2.0)
        if summ:
            results_list.append({"param": "slippage", "value": "2.0x", "pf": summ["pf"], "n": summ["n"]})
            
        base_params = copy.deepcopy(strat.params)
        for p_name, p_val in base_params.items():
            if isinstance(p_val, (int, float)):
                for mult in [0.8, 1.2]:
                    new_val = p_val * mult
                    if isinstance(p_val, int):
                        new_val = int(new_val)
                    strat.params = copy.deepcopy(base_params)
                    strat.params[p_name] = new_val
                    summ = run_strat(strat)
                    if summ:
                        results_list.append({"param": p_name, "value": f"{new_val} ({mult}x)", "pf": summ["pf"], "n": summ["n"]})
        
        strat.params = base_params
        
        out_json = Path("results") / f"robustness_{strat_name}.json"
        with open(out_json, "w") as f:
            json.dump(results_list, f, indent=2)

if __name__ == "__main__":
    main()
