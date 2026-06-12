# Two-Track Stock Strategy Research Program — Design Spec

**Date:** 2026-06-12
**Status:** Approved by Austin (design presented and accepted in session)
**Goal:** Find swing-trade and day-trade stock strategies that pass the established
evaluation gate on free data, with anti-overfit validation the prior crypto work lacked.

## Context

- Prior crypto/Kalshi research established the evaluation framework: **PF > 1.3,
  ≥500 trades, rank by PF + win rate; drawdown reported but not gating.**
- Account: under $25k. The PDT rule was eliminated June 4, 2026 (FINRA Notice 26-10);
  day trading is regulatorily viable, but broker phase-in runs through Oct 2027.
- Data budget: **free only.** This fully powers daily-bar research (decades of history)
  and limits intraday research (~730 days of 1h bars, ~60 days of 5m bars via Yahoo).
- Risk tolerance: high. Leveraged ETFs and concentrated positions are in scope.
- Options: **deferred.** No free historical options-chain data of usable quality exists;
  options become an execution/leverage layer on validated directional signals later.
- Execution mechanics: undecided by design — research is the deliverable.

## Architecture

New standalone repo at `~/stocks-research`. No freqtrade dependency (crypto-only).
Python 3.14 venv. Custom vectorized backtest harness (pandas 3.x rules out
vectorbt/backtesting.py off the shelf, and the harness must be auditable anyway).

```
stocks-research/
├── docs/superpowers/specs/      this spec; plans
├── data/                        parquet cache (gitignored)
├── src/stockslab/
│   ├── data.py                  yfinance fetch + parquet cache + universe lists
│   ├── indicators.py            EMA/SMA/RSI/ATR/Donchian/BBands/VWAP in numpy/pandas
│   ├── engine.py                vectorized backtester (see semantics below)
│   ├── mm/                      ported from ~/mm-bot/mm/ (sizing, heat, regime)
│   ├── metrics.py               PF, win rate, DD, trade stats, gate evaluation
│   └── strategies/              one file per strategy, auto-discovered registry
├── scripts/
│   ├── fetch_data.py            download + cache universe
│   ├── run_backtests.py         run all strategies × universe × IS/OOS splits
│   └── make_report.py           ranked report from results
├── results/                     per-run JSON/CSV (gitignored except summaries)
├── tests/                       pytest; engine reference cases are the core
└── docs/REPORT.md               final ranked findings
```

## Backtest engine semantics (anti-lookahead contract)

These rules are the correctness core; engine tests enforce each one:

1. Signals computed on bar *t* close → entry at bar *t+1* **open**, slippage applied.
2. Stops/targets evaluated intrabar on OHLC. If a bar touches both stop and target,
   **assume stop fills first** (conservative).
3. Gap through stop → fill at the open (not the stop price).
4. Sizing: fixed-fractional risk per trade (default 1% of equity), shares floored,
   never rounded up (port of `mm-bot/mm/sizing.py`). PF/WR stats are computed in
   R-multiples so ranking is sizing-independent; equity curves shown at 1% risk.
5. Costs: commission $0; slippage in bps by liquidity tier — 1 bp (major ETFs),
   3 bps (megacap stocks), 5 bps (other stocks / leveraged ETFs), per side.
6. Max concurrent positions + portfolio heat cap (port of `mm/heat.py`).
7. No indicator may read past its bar (enforced by shift-discipline tests).
8. Two strategy interfaces:
   - **Signal-based** (default): per-symbol entry/exit/stop signals as in rules 1–3.
   - **Rotation-based** (`xsec_momentum`, `sector_rotation`): target holdings emitted
     at rebalance close, filled at next open; each position entered counts as one trade.
9. Open-signal entries (`gap_fade`): a signal may be computed *from bar t's open*
   (gap size is observable at the open) and filled at that same open + slippage.
   The signal function receives only `open` for bar t, never high/low/close.

## Data

- **Source:** yfinance (no API key). Backoff + local parquet cache; Stooq as a
  daily-bars fallback if Yahoo rate-limits.
- **Universe:**
  - ETFs (no survivorship bias): SPY, QQQ, IWM, DIA, XLK, XLF, XLE, XLV, XLI, XLP,
    XLU, XLY, XLB, XLRE, XLC, GLD, SLV, TLT, HYG, EEM, EFA;
    leveraged: TQQQ, SQQQ, SOXL, SOXS, UPRO, TNA, UVXY.
  - Stocks: current S&P 100 + ~30 liquid high-beta names (NVDA, TSLA, AMD, PLTR, …).
    **Known limitation: survivorship bias** (today's constituents tested on history).
    Documented in the report; ETF results carry no such bias and are weighted
    accordingly in conclusions.
- **History:** daily from 2000-01-01 (or inception); 1h for trailing 730 days;
  5m for trailing 60 days.

## Splits and gates

| | In-sample | Out-of-sample |
|---|---|---|
| Daily track | 2010-01-01 → 2021-12-31 | 2022-01-01 → 2026-06-01 |
| 1h track | first 70% of 730d | last 30% |
| 5m track | report-only (too thin to gate) | — |

**Phase-1 gate (IS, aggregate across universe):** PF > 1.3 AND trades ≥ 500.
**Phase-2 validation (survivors only):**
- OOS: PF > 1.15 with trade frequency consistent with IS.
- Parameter sensitivity: every knob perturbed ±20%; PF must stay > 1.15.
- Cost stress: 2× slippage; PF must stay > 1.1.
A strategy is a **finding** only if it passes all of Phase 2. Drawdown is reported,
not gating (per standing decision). No funding-rate-style strategies (N/A for stocks).

## Strategy candidates (12)

Swing track (daily bars):
1. `donchian_breakout` — 55d-high entry, ATR trail / 20d-low exit (turtle-style).
2. `ema_pullback` — port of mm_steady: EMA50>EMA200 uptrend, pullback toward EMA20
   with RSI<40, ATR stop, 2R target.
3. `rsi2_meanrev` — Connors: close>SMA200, buy RSI(2)<10, exit RSI(2)>70 or close>SMA5.
4. `bb_squeeze_breakout` — BB-width percentile squeeze, trade the breakout direction.
5. `xsec_momentum` — weekly rotation, top-k stocks by 12-1 momentum, regime filter.
6. `sector_rotation` — weekly top-3 sector ETFs by blended momentum, SPY regime filter.
7. `gap_fade` — uptrend stock gaps down >2% at open → buy open, exit same close
   (daily-OHLC implementable).
8. `levered_etf_meanrev` — TQQQ/SOXL z-score/RSI(2) dip-buy while QQQ above SMA200.
9. `high52_breakout` — new 52-week high with volume expansion, ATR trail.

Intraday track (1h bars; 5m where it exists):
10. `orb` — opening-range breakout (first-hour range on 1h; 30-min ORB on 5m/60d).
11. `vwap_reclaim` — reclaim of session VWAP from below in an up-regime.
12. `intraday_momentum` — first-hour return predicts last-hour move (SPY/QQQ).

## Orchestration (approved model plan)

Per the standing model-selection rule — agent counts and tiers chosen by task fit:

- **Phase A — infra** (data, engine, mm port, metrics; TDD): 2–3 **Sonnet** agents.
  Code writing against a precise spec = moderate reasoning.
- **Engine adversarial review:** 1–2 **Opus** agents hunting lookahead bias and
  off-by-one errors before any strategy is trusted. High-stakes judgment.
- **Phase B — strategies:** up to 12 parallel **Sonnet** agents, one per strategy,
  disjoint files against a frozen harness API.
- **Phase C — backtest runs:** plain scripts, no agents.
- **Phase D — verification + synthesis:** 3–4 **Opus** agents (overfit critique,
  robustness audit, report synthesis).
- No Haiku: no pure-retrieval subtasks exist in this program.

Total ≈ 18–22 agents. Approved in session 2026-06-12.

## Deliverables

1. `docs/REPORT.md` — ranked findings: per-strategy IS/OOS PF, win rate, trade count,
   max DD, sensitivity and cost-stress outcomes, with survivorship/thin-data caveats.
2. Reproducible repo: `fetch_data.py` → `run_backtests.py` → `make_report.py`
   regenerates everything.
3. Honest negative results: strategies that fail are reported as failed, not tuned
   until they pass (tuning = overfitting).

## Risks

- **Survivorship bias** in the stock list (mitigated: ETF-heavy conclusions, documented).
- **yfinance reliability** (mitigated: cache, backoff, Stooq fallback for daily).
- **Thin intraday history** — intraday findings are provisional by construction.
- **Regime concentration** — 2010–2021 IS is mostly bull market; OOS includes 2022
  bear and 2024–2026, which is exactly why the OOS gate exists.
