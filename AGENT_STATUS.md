# Agent Status

Coordination file for the three-agent lane split.
Each agent owns its section. Only write to your own section.
Human (Austin) is the courier — paste agent output back into this file when they finish.

---

## Claude — engine / research lane

**Last updated:** 2026-06-12
**Status:** IDLE — waiting for next task

### Done this session
- Drafted result contract v0.1.0 → revised to v0.2.0 folding in Codex's 7 requests
- Added watchlist/scanner forward-compat fields
- Wrote validator (`contracts/validate.py`) — 5 schema guards enforced, green
- Wrote contracts/ artifacts: schema, examples, spec doc, README

### Open (engine lane)
- [ ] **Commit `contracts/`** — untracked; schema + spec + examples + validate.py + README
- [ ] **Push to origin** — 17+ commits ahead of origin/main

### Resolved
- [x] **Q4 bar-label check** (2026-06-12) — **BAR-START**. Index label = bar open time. `09:30` = opens 9:30, closes 10:30. Timezone: `America/New_York`. 7 bars/day (09:30–15:30). Contract `entry_time` / `exit_time` fields should be interpreted as bar-open timestamps.

### Blocking on
Nothing currently.

### Notes for next session
- `scripts/robustness.py` has uncommitted modifications (not mine — don't touch without knowing what they are)
- jsonschema is installed in .venv but NOT in requirements.txt — dev-only; was supposed to be added by AGY

---

## Codex — copilot lane

**Last updated:** 2026-06-12
**Status:** TASK READY

### Done
- Reviewed result contract v0.2.0
- Confirmed 7 requests were incorporated
- Signed off on 3 open judgment calls

### Open
- [ ] **Build results dashboard** — see task below

### Task: Build results dashboard (`docs/dashboard_results.html`)

Build a standalone HTML file that visualizes all 12 strategy backtest results. No build step — pure HTML + inline JS + Chart.js from CDN.

**Data sources (all local, relative paths):**
- `results/{strategy}_IS.json` — keys: `pf`, `wr`, `n`, `avg_r`, `med_hold_bars`, `max_dd_1pct`, `exit_reason_counts`
- `results/{strategy}_OOS.json` — same keys
- `results/{strategy}_IS_trades.csv` — cols: `symbol,entry_date,exit_date,entry,exit,shares,r_multiple,pct_return,exit_reason`
- `results/robustness_{strategy}.json` — exists for 4 survivors only; keys: `param`, `value`, `pf`, `n`

**The 12 strategies:** `bb_squeeze_breakout`, `donchian_breakout`, `ema_pullback`, `gap_fade`, `high52_breakout`, `intraday_momentum`, `levered_etf_meanrev`, `orb`, `rsi2_meanrev`, `sector_rotation`, `vwap_reclaim`, `xsec_momentum`

**Gate thresholds:** IS PF > 1.3 AND N >= 500 AND OOS PF > 1.15

**Sections to build:**

1. **Gate summary table** — one row per strategy. Columns: Strategy, IS PF, IS N, OOS PF, Status (PASS/FAIL, colour-coded green/red). Sort by IS PF descending. Clicking a row expands the detail panel below.

2. **Equity curves** (survivors only: xsec_momentum, donchian_breakout, high52_breakout, bb_squeeze_breakout) — load trades CSV, compute cumulative sum of r_multiple sorted by exit_date, plot as line chart with Chart.js. One chart per strategy, all on same page.

3. **Exit reason breakdown** — stacked bar chart per strategy, using `exit_reason_counts` from the IS JSON. Reasons: stop, signal, gap_stop, target, time, session, eod.

4. **Robustness sensitivity** (4 survivors only) — for each `robustness_{strategy}.json`, plot a bar chart: x=param+value label, y=PF. Draw a horizontal dashed line at PF=1.3 (gate floor).

**Implementation notes:**
- Load JSON/CSV with `fetch()` at runtime — the file must be opened via a local HTTP server or `file://` with CORS disabled. Add a note at the top of the page: "Serve with: `python3 -m http.server 8080` from the project root"
- Parse CSV manually or use a 50-line Papa Parse CDN include — your call
- Dark theme preferred (matches the existing `dashboard.html` style)
- No React, no bundler, no npm — single file only

**When done:** update your section in `AGENT_STATUS.md` with status and any issues.

---

## AGY — mechanical lane

**Last updated:** 2026-06-12
**Status:** TASKS READY

### Done
- Implemented result emitter (9774a2b)
- Wired emitter into backtest runner (443432c)
- Added permanent schema guard tests (b367efe)
- Added `jsonschema` to `requirements.txt` (bb4e4ca)

### Open
- [ ] **Fix `ema_pullback` — only 15 IS trades (bug)** — see Task 1 below
- [ ] **Investigate `levered_etf_meanrev` OOS > IS anomaly** — see Task 2 below

### Task 1: Fix `ema_pullback` (only 15 IS trades — signal bug)

**Context:** `ema_pullback` produced only 15 trades over 11 years on 100+ stocks. This is almost certainly a bug — the spec says `rsi(14) < 40` which should fire regularly in an uptrend universe.

**Spec rule (from docs/superpowers/plans/2026-06-12-two-track-stock-research.md):**
Strategy 2: uptrend = `ema50 > ema200 and close > ema50`; entry when uptrend AND `low <= ema20` AND `rsi(14) < 40`; stop_dist = `1.5 * atr(14)`; target_r = 2.0; time_stop_bars = 15.

**Files:**
- `src/stockslab/strategies/ema_pullback.py` — implementation to inspect
- `src/stockslab/indicators.py` — indicator implementations
- `results/ema_pullback_IS.json` — shows n=15

**Your tasks:**
1. Read `ema_pullback.py` and compare every condition to the spec rule above
2. Run a diagnostic: `.venv/bin/python -c "import pandas as pd; from src.stockslab.strategies.ema_pullback import EMAMPullback; from src.stockslab import data; df = data.load_panel(['AAPL'], '1d')['AAPL']; sigs = EMAMPullback().generate(df); print(sigs['entry_long'].sum(), 'signals on AAPL')"` — if < 10 signals on AAPL alone, the filter is too tight
3. Identify the bug (likely: wrong RSI period, wrong EMA period, or a compound condition that evaluates False always)
4. Fix the bug in `src/stockslab/strategies/ema_pullback.py`
5. Re-run just this strategy: `.venv/bin/python scripts/run_backtests.py --strategies ema_pullback` and verify trade count is now in the hundreds+
6. Update `results/ema_pullback_IS.json`, `_OOS.json`, and trade CSVs with the corrected run

**When done:** update `AGENT_STATUS.md` AGY section with: bug found, fix applied, new trade count, new IS PF.

### Task 2: Investigate `levered_etf_meanrev` OOS > IS anomaly

**Context:** `levered_etf_meanrev` has IS PF=1.116 (failed gate) but OOS PF=1.556. OOS outperforming IS is unusual — could mean the IS period was a bad regime for this strategy, or there's a subtle data issue.

**Spec rule:** entry when `QQQ.close > QQQ.sma200` AND `rsi(2) < 10` on the levered ETF (TQQQ/SOXL/UPRO/TNA); exit when `rsi(2) > 65`; stop_dist = `3 * atr(14)`; time_stop_bars = 10. Universe: levered ETFs only.

**IS split:** 2010-01-01 to 2021-12-31. **OOS split:** 2022-01-01 to 2026-06-01.

**Files:**
- `results/levered_etf_meanrev_IS_trades.csv` and `_OOS_trades.csv`
- `src/stockslab/strategies/levered_etf_meanrev.py`

**Your tasks:**
1. Load both trade CSVs. Compute PF per year: `group by year(entry_date), compute pf`. Print the year-by-year PF table — this reveals if IS had one bad year dragging it down, or if OOS genuinely outperformed.
2. Check symbol distribution: are the OOS trades concentrated in a single ETF that happened to trend well post-2022?
3. Check the QQQ filter is working: are there trades during 2022 drawdown (when QQQ < sma200)? If yes, the filter is broken.
4. Write findings to `AGENT_STATUS.md` AGY section. Do NOT rerun the strategy — just report findings. Claude will decide whether to re-run.

**When done:** update `AGENT_STATUS.md` AGY section with year-by-year PF table, symbol breakdown, and QQQ filter verdict.

---

## Shared context

### Lane boundaries
- **Claude** = strategy research, contract spec, data analysis, architecture decisions
- **Codex** = code implementation, refactors, test writing, anything touching src/
- **AGY** = mechanical tasks: schema work, boilerplate, file generation, requirements

### Key files
- `contracts/result_contract_v0.md` — full spec; §10 = open decisions, §14 = AGY tasks
- `contracts/result_contract.schema.json` — JSON schema (validate with `contracts/validate.py`)
- `docs/superpowers/plans/2026-06-12-two-track-stock-research.md` — strategy rules
- `.venv/` — Python env; always use `.venv/bin/python`

### How to use this file
1. Read your section and the Shared context before starting any task
2. Check other agents' sections for blockers or outputs you depend on
3. Write your status update in your own section when done
4. Human pastes update back into this file and commits
