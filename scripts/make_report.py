import json
from pathlib import Path

def main():
    results_dir = Path("results")
    if not results_dir.exists():
        print("No results directory found.")
        return

    strategies = set()
    for p in results_dir.glob("*_IS.json"):
        strategies.add(p.stem.replace("_IS", ""))

    rows = []
    
    for strat in sorted(strategies):
        is_file = results_dir / f"{strat}_IS.json"
        oos_file = results_dir / f"{strat}_OOS.json"
        rob_file = results_dir / f"robustness_{strat}.json"
        
        if is_file.exists():
            with open(is_file) as f:
                is_sum = json.load(f)
        else:
            continue
            
        oos_sum = None
        if oos_file.exists():
            with open(oos_file) as f:
                oos_sum = json.load(f)
                
        rob_data = []
        if rob_file.exists():
            with open(rob_file) as f:
                rob_data = json.load(f)
                
        is_pf = is_sum.get("pf", 0)
        is_wr = is_sum.get("wr", 0)
        is_n = is_sum.get("n", 0)
        is_maxdd = is_sum.get("max_dd_1pct", 0)
        
        oos_pf = oos_sum.get("pf", 0) if oos_sum else 0
        oos_wr = oos_sum.get("wr", 0) if oos_sum else 0
        oos_n = oos_sum.get("n", 0) if oos_sum else 0
        
        min_pf = min([d["pf"] for d in rob_data if d["param"] != "slippage"], default=is_pf)
        slip2x_pf = next((d["pf"] for d in rob_data if d["param"] == "slippage"), 0)
        
        verdict = "Fail"
        if is_pf > 1.3 and is_n >= 500:
            verdict = "Pass IS"
            if oos_pf > 1.15:
                verdict = "Pass OOS"
                
        rows.append({
            "strat": strat,
            "is_pf": is_pf,
            "is_wr": is_wr,
            "is_n": is_n,
            "oos_pf": oos_pf,
            "oos_wr": oos_wr,
            "oos_n": oos_n,
            "maxdd": is_maxdd,
            "min_pf": min_pf,
            "slip2x_pf": slip2x_pf,
            "verdict": verdict
        })

    # Sort by IS PF
    rows.sort(key=lambda x: x["is_pf"], reverse=True)

    md = ["# Stockslab Phase C Report\n"]
    md.append("## Strategy Rankings\n")
    md.append("| Strategy | IS PF | IS WR | IS N | OOS PF | OOS WR | OOS N | IS MaxDD(1%) | Min Rob PF | 2x Slip PF | Verdict |")
    md.append("|---|---|---|---|---|---|---|---|---|---|---|")
    
    for r in rows:
        md.append(f"| {r['strat']} | {r['is_pf']:.2f} | {r['is_wr']:.2%} | {r['is_n']} | "
                  f"{r['oos_pf']:.2f} | {r['oos_wr']:.2%} | {r['oos_n']} | {r['maxdd']:.2%} | "
                  f"{r['min_pf']:.2f} | {r['slip2x_pf']:.2f} | {r['verdict']} |")

    md.append("\n## Caveats\n")
    md.append("- **Survivorship Bias**: Daily historical data does not include delisted symbols.\n")
    md.append("- **Thin Intraday Data**: The intraday data window is short and recent.\n")
    md.append("- **Regime Dependence**: The out-of-sample window may just be a different regime.\n")
    
    Path("docs").mkdir(exist_ok=True)
    with open("docs/REPORT.md", "w") as f:
        f.write("\n".join(md))
    print("Report written to docs/REPORT.md")

if __name__ == "__main__":
    main()
