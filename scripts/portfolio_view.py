#!/usr/bin/env python
"""Concurrency-aware portfolio view for generated trade ledgers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from stockslab.engine import Trade
from stockslab import metrics


def load_trades(path: Path) -> list[Trade]:
    df = pd.read_csv(path, parse_dates=["entry_date", "exit_date"])
    trades: list[Trade] = []
    for row in df.itertuples(index=False):
        trades.append(
            Trade(
                symbol=row.symbol,
                entry_date=pd.Timestamp(row.entry_date),
                exit_date=pd.Timestamp(row.exit_date),
                entry=float(row.entry),
                exit=float(row.exit),
                shares=float(row.shares),
                r_multiple=float(row.r_multiple),
                pct_return=float(row.pct_return),
                exit_reason=str(row.exit_reason),
            )
        )
    return trades


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategies", nargs="+", required=True)
    parser.add_argument("--splits", nargs="+", default=["IS", "OOS"], choices=["IS", "OOS"])
    parser.add_argument("--risk-frac", type=float, default=0.01)
    args = parser.parse_args()

    for strategy in args.strategies:
        for split in args.splits:
            path = Path("results") / f"{strategy}_{split}_trades.csv"
            trades = load_trades(path)
            timeline = metrics.portfolio_timeline_summary(trades, risk_frac=args.risk_frac)
            summary_path = Path("results") / f"{strategy}_{split}.json"
            with summary_path.open() as f:
                legacy_dd = json.load(f)["max_dd_1pct"]
            print(
                f"{strategy} {split}: "
                f"peak_concurrency={timeline['peak_concurrent_positions']} "
                f"peak_open_risk={timeline['peak_open_risk_frac']:.2%} "
                f"calendar_dd={timeline['max_dd']:.4f} "
                f"legacy_dd={legacy_dd:.4f}"
            )


if __name__ == "__main__":
    main()
