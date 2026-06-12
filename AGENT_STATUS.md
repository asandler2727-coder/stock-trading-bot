# Agent Status

Coordination file for the three-agent lane split.
Each agent owns its section. Only write to your own section.
Human (Austin) is the courier — paste agent output back into this file when they finish.

---

## Claude — engine / research lane

**Last updated:** 2026-06-12
**Status:** ACTIVE

### Done this session
- Drafted result contract v0.1.0 → revised to v0.2.0; contracts/ committed
- Phase D Kanban audits (D1 ×4, D2 synthesis) — all done; `docs/REPORT_D2.md` written
- Digested AGY findings; updated canonical `ema_pullback_IS.json` / `_OOS.json` from new trade CSVs
- Ran robustness sweep for ema_pullback → `results/robustness_ema_pullback.json`
- Diagnosed ema_pullback "param bug" → it's spec drift, not wiring (proof in `/tmp/diag_ema.py`); handed Codex a sharpened read-only task
- Digested Codex spec review: donchian + high52 spec-clean (gate CLEARED); ema_pullback drift confirmed + vacuous test found; xsec off-by-one + holiday bugs confirmed (already known)
- **Engine checkpoint — VERIFIED Codex's `rsi_dip_uptrend` rework:** independently reran it — IS reproduces exactly (PF 1.3872 / n 5423), OOS holds (PF 1.2902 / n 1649), my numbers match Codex's to the digit; new test passes + Codex's full suite is 262 green; rename clean repo-wide. Edge survived → re-enters ranking at #3.

### Phase D results

**5 gate passers (ema_pullback added after AGY bug fix):**

| Strategy | IS PF | IS N | OOS PF | Min robustness PF | Verdict |
|---|---|---|---|---|---|
| xsec_momentum | 3.326 | 651 | 2.212 | — | REVIEW (regime + concentration) |
| donchian_breakout | 1.624 | 2698 | 1.361 | 1.50 | CONFIRM |
| high52_breakout | 1.515 | 812 | 1.322 | — | CONFIRM |
| rsi_dip_uptrend (was ema_pullback) | 1.387 | 5423 | 1.290 | 1.28 | ✅ REWORKED — RSI-dip; edge Claude-verified |
| bb_squeeze_breakout | 1.313 | 1471 | 1.171 | — | REVIEW (marginal edge) |

**ema_pullback details:**
- Bug: `close > ema50` was mutually exclusive with `rsi(14) < 40` — fixed by AGY (now uses `close > ema200`)
- Robustness: param sweeps hold PF ≥ 1.28. At 2× slippage: PF=1.327 (barely holds). **Caveat: only 5 of 7 knobs were actually tested** — see inertness finding.
- **RESOLVED — the ema_fast/ema_mid identical-PF "smell" is NOT a wiring bug.** Params are correctly wired (`ema_fast`→ema20 line 27, `ema_mid`→ema50 line 28); `ema_slow`→ema200 uses the same pattern and *does* move the sweep, proving overrides reach `generate()`. Diagnostic (`/tmp/diag_ema.py`, full IS universe) shows **both conditions those params feed are inert** — deltas exactly 0:
  - Dropping `low <= ema20` (the namesake *pullback*) changes 0 signals → implied by `rsi(14) < 40` on 100% of qualifying bars. `ema_fast` is a dead knob.
  - Dropping `(ema50 > ema200)` changes 0 signals → implied by `close > ema200`. `ema_mid` is a dead knob.
- **Spec drift (matters for go/no-go):** AGY's fix over-relaxed. The strategy is now operationally identical to `entry = (close > ema200) & (rsi(14) < 40)` — an RSI-dip-in-long-uptrend play, *not* the spec's EMA-stacked pullback (spec line 216: `uptrend = ema50>ema200 and close>ema50`). Real param sensitivity lives in `rsi_thresh` (32→PF 1.527/n 974; 48→PF 1.283/n 13199) and `ema_slow`. The "robustness holds" claim is weaker than it reads: 2 of 7 sweeps were no-ops, so they demonstrate nothing.
- **Stale/vacuous test (Codex flagged, Claude verified):** `tests/test_strat_ema_pullback.py:51` still encodes the old spec `close > ema50`. Suite is GREEN, but `test_entry_requires_all_three_conditions` passes *vacuously* — the synthetic random-walk fixture yields **0 entries**, so it would pass against any uptrend formula. Zero protection against the drift. Whichever design path Austin picks, this test must be rewritten with entry-generating data + the chosen spec.

**D2 report corrections (two errors in `docs/REPORT_D2.md`):**
1. D2 called ema_pullback "not viable" — now gate passer #5 after the bug fix
2. D2 called levered_etf_meanrev OOS>IS "data mining" — AGY confirmed it's the QQQ filter working correctly (filter blocked all 2022 trades; 2018 PF=0.57, 2019 PF=0.78 hurt IS). Still a gate fail (IS PF=1.116) but mechanically explained, not overfit

**Paper-trade ranking:**
1. **donchian_breakout** — highest confidence; 2698 trades; simplest logic; cleanest audit
2. **high52_breakout** — clean audit; strong diversification
3. **rsi_dip_uptrend** (was ema_pullback) — ✅ REWORKED + VERIFIED. Accepted as the RSI-dip strategy it is; Codex renamed + simplified to `close>ema200 & rsi(14)<40`, Claude confirmed IS reproduces exactly (PF 1.387 / n 5423) and OOS holds (PF 1.290 / n 1649). Real robustness rests on rsi_thresh + ema_slow (dropped ema_fast/ema_mid were inert). Largest trade count of the set (5423).
4. **xsec_momentum** — strong edge but needs regime detection + position sizing controls
5. **bb_squeeze_breakout** — most marginal; lowest priority

### Open (engine lane)
- [x] ~~Paper-trade go/no-go for donchian + high52~~ — **APPROVED GO on both (Austin, this session).** Spec-clean (Codex + D2), robust above gate IS+OOS+2× slippage. NOTE: donchian max DD @1% risk = 71.6% → wants fractional sizing. high52 = 27.7%, the smooth one. **No paper-trade harness exists yet → next build.**
- [ ] **Build paper-trade harness** for donchian + high52: position sizing (donchian needs ≤0.5% risk), result-contract wiring, monitoring. Scope deliberately — greenfield.
- [x] ~~Codex task: verify ema_pullback params wired~~ — RESOLVED by Claude: wired correctly, but conditions inert (see details). Now a strategy-design decision, not a wiring fix.
- [x] ~~ema_pullback design decision~~ — **DECIDED (Austin): accept as RSI-dip.** Codex task issued: rename/re-spec to reflect it's an RSI-dip-in-uptrend strategy, drop dead ema_fast/ema_mid params, rewrite the vacuous test with entry-generating data.
- [x] ~~ema_pullback → rsi_dip_uptrend rework + OOS confirm~~ — **DONE + Claude-VERIFIED.** Codex shipped the rename/refactor; Claude reran (IS 1.3872/5423 exact, OOS 1.2902/1649 holds, 262 tests green). Strategy is real, just honestly named now.
- [ ] xsec_momentum (if ever promoted): fix confirmed off-by-one momentum index + Monday-holiday rebalance fallback. Not blocking — it's ranked #4, needs regime/sizing controls first.
- [ ] levered_etf_meanrev: consider re-evaluation with longer IS window (low priority)

---

## Codex — copilot lane

**Last updated:** 2026-06-12
**Status:** IDLE

### Done
- Reviewed result contract v0.2.0; signed off on 7 requests + 3 judgment calls
- Built `docs/dashboard_results.html` (12 gate rows, equity curves, exit breakdowns, robustness charts)
- Completed read-only spec-vs-implementation review of the 5 current gate passers
- Confirmed Claude's `ema_pullback` param diagnosis with `/tmp/diag_ema.py`
- Completed `ema_pullback` → `rsi_dip_uptrend` rework: renamed strategy/test/results, removed dead `ema_fast`/`ema_mid` params, implemented canonical RSI-dip rule, rewrote non-vacuous tests, updated spec docs/report/dashboard, regenerated IS/OOS/robustness outputs

### Open
- (None)

### Rework results

- New strategy name: `rsi_dip_uptrend`
- Canonical rule now implemented: `entry_long = (close > ema200) & (rsi(rsi_n) < rsi_thresh) & atr.notna()`
- IS reproduced: PF `1.3872470088066529`, N `5423`
- OOS result: PF `1.2901913080388698`, N `1649`
- OOS did not materially shift from prior `~1.290`; the removed conditions were zero-delta as expected
- Robustness regenerated without dead EMA knobs; 2x slippage PF `1.3273892008693449`, min non-slippage robustness PF `1.2845276326066997`
- Full test suite: `262 passed`
- Dashboard verified at `http://localhost:8080/docs/dashboard_results.html`: 12 rows, 11 charts, `Rsi Dip Uptrend` row present, no browser console errors, no mobile page overflow
- Not paper-trade-ready by Codex decision; hand back to Claude to confirm the edge survived before re-entering the ranking

### Issues / notes
- Dashboard `fetch()` — serve from project root: `python3 -m http.server 8080`
- Retired generated `ema_pullback` result artifacts were removed so scans/reporting use only `rsi_dip_uptrend`

### Historical strategy review findings (pre-rename)

Sub-task 1 confirmation: I agree with Claude. `ema_fast`, `ema_mid`, and `ema_slow` are wired into the EMA calls, so this is not a param plumbing bug. The diagnostic reproduced exactly: base signals 15,354; dropping `low <= ema20` changed 0 signals; dropping `ema50 > ema200` changed 0 signals; `ema_fast` 16/20/24 and `ema_mid` 40/50/60 all produced 15,354 signal bars.

Resolution: Austin chose the accept-as-RSI-dip path. The implementation is now `rsi_dip_uptrend`; this block is preserved as the review trail that led to the rename.

| Strategy | Spec match? | Deviations / notes |
|---|---|---|
| donchian_breakout | Yes | Matches spec: entry `close > donchian_high(55).shift(1)`, exit `close < donchian_low(20).shift(1)`, stop `2*atr(14)`, trail 3, no time stop. My read agrees with D2's clean audit. |
| high52_breakout | Yes | Matches spec: entry `high >= rolling_max(high,252).shift(1)` plus `volume > 1.5*sma(volume,50)`, stop `2*atr(14)`, trail 3, no explicit signal/time exit. My read agrees with D2's clean audit. |
| ema_pullback | No | Stop `1.5*atr(14)`, target 2R, and time stop 15 match. Entry drift is material: implementation uses `(ema50 > ema200) & (close > ema200) & (low <= ema20) & (rsi14 < 40)`, not spec `(ema50 > ema200) & (close > ema50) & (low <= ema20) & (rsi14 < 40)`. In current data, `low <= ema20` and `ema50 > ema200` are inert after the AGY relaxation, so the strategy behaves like `close > ema200 & rsi14 < 40`. D2 is stale here: it audited the old 15-trade failure, not the fixed 5,423-trade passer. Existing test `tests/test_strat_ema_pullback.py` still encodes the spec's `close > ema50` condition, so tests/spec and implementation are now out of sync. |
| xsec_momentum | Partial | Broad spec matches: stock rotation, top 10, SPY regime filter, rotation exits, no explicit stop/time stop. D2's two logic caveats are real: momentum indexing is off by one versus literal `close.shift(21)/close.shift(252)-1` because code uses `hist.iloc[-21] / hist.iloc[-252] - 1`; and rebalance dates are only Mondays present in the data, so Monday market holidays skip that week instead of falling back to the next trading day. |
| bb_squeeze_breakout | Yes | Matches spec: squeeze uses BB width in the lowest 15th percentile of trailing 252, entry requires prior-bar squeeze and current `close > bb_upper`, stop `2*atr(14)`, trail 2.5, no explicit signal/time exit. My read agrees with D2 that logic matches; edge remains marginal, but that is performance risk rather than spec drift. |

### Task: Build results dashboard (`docs/dashboard_results.html`)

Build a standalone HTML file that visualizes all 12 strategy backtest results. No build step — pure HTML + inline JS + Chart.js from CDN.

**Data sources (all local, relative paths):**
- `results/{strategy}_IS.json` — keys: `pf`, `wr`, `n`, `avg_r`, `med_hold_bars`, `max_dd_1pct`, `exit_reason_counts`
- `results/{strategy}_OOS.json` — same keys
- `results/{strategy}_IS_trades.csv` — cols: `symbol,entry_date,exit_date,entry,exit,shares,r_multiple,pct_return,exit_reason`
- `results/robustness_{strategy}.json` — exists for 4 survivors only; keys: `param`, `value`, `pf`, `n`

**The 12 strategies:** `bb_squeeze_breakout`, `donchian_breakout`, `rsi_dip_uptrend`, `gap_fade`, `high52_breakout`, `intraday_momentum`, `levered_etf_meanrev`, `orb`, `rsi2_meanrev`, `sector_rotation`, `vwap_reclaim`, `xsec_momentum`

**Gate thresholds:** IS PF > 1.3 AND N >= 500 AND OOS PF > 1.15

**Sections to build:**

1. **Gate summary table** — one row per strategy. Columns: Strategy, IS PF, IS N, OOS PF, Status (PASS/FAIL, colour-coded green/red). Sort by IS PF descending. Clicking a row expands the detail panel below.

2. **Equity curves** (survivors only: xsec_momentum, donchian_breakout, high52_breakout, rsi_dip_uptrend, bb_squeeze_breakout) — load trades CSV, compute cumulative sum of r_multiple sorted by exit_date, plot as line chart with Chart.js. One chart per strategy, all on same page.

3. **Exit reason breakdown** — stacked bar chart per strategy, using `exit_reason_counts` from the IS JSON. Reasons: stop, signal, gap_stop, target, time, session, eod.

4. **Robustness sensitivity** (5 survivors only) — for each `robustness_{strategy}.json`, plot a bar chart: x=param+value label, y=PF. Draw a horizontal dashed line at PF=1.3 (gate floor).

**Implementation notes:**
- Load JSON/CSV with `fetch()` at runtime — the file must be opened via a local HTTP server or `file://` with CORS disabled. Add a note at the top of the page: "Serve with: `python3 -m http.server 8080` from the project root"
- Parse CSV manually or use a 50-line Papa Parse CDN include — your call
- Dark theme preferred (matches the existing `dashboard.html` style)
- No React, no bundler, no npm — single file only

**When done:** update your section in `AGENT_STATUS.md` with status and any issues.

---

## AGY — mechanical lane

**Last updated:** 2026-06-12
**Status:** NEW TASK — independent verification of paper-trade candidates (donchian + high52)

### Done
- Implemented result emitter (9774a2b)
- Wired emitter into backtest runner (443432c)
- Added permanent schema guard tests (b367efe)
- Added `jsonschema` to `requirements.txt` (bb4e4ca)
- **Fix `ema_pullback`**: Bug found where `close > ema50` in the uptrend condition was mutually exclusive with `rsi(14) < 40`. Fixed by relaxing the uptrend condition to `close > ema200`. New IS trade count: 5423, New IS PF: 1.39.
- **Investigate `levered_etf_meanrev`**:
  - **Year-by-year PF**: IS had a few bad years (e.g., 2018: 0.569, 2019: 0.775).
  - **Symbol breakdown**: OOS trades are widely distributed (SQQQ: 52, SOXS: 51, UVXY: 49, TNA: 42, UPRO: 38, QQQ: 36, TQQQ: 35, SOXL: 35). Not concentrated in a single ETF, though bear ETFs are heavily represented.
  - **QQQ filter verdict**: The filter is working perfectly. There were exactly 0 trades in 2022 because QQQ was below its 200-day SMA. This entirely bypassed the 2022 bear market, which is why OOS outperformed IS.

### Open
- [ ] **Independent verification battery** (donchian + high52) — extra eyes before paper trade; see task below

### Task: Independent verification of paper-trade candidates (READ-ONLY)

**Why:** `donchian_breakout` + `high52_breakout` are APPROVED GO for paper trading. Before real-money-adjacent use we want an independent mechanical re-check — Codex reviewed spec-vs-code (logic) and Claude did the strategy diagnosis, but **nobody has independently recomputed the headline numbers from the raw trade ledgers or audited the underlying data.** That's the gap you fill.

**Hard constraints:**
- **READ-ONLY.** Recompute and report. Do NOT modify result JSONs, trade CSVs, or `src/`.
- **Scope = `donchian_breakout` and `high52_breakout` ONLY.** Do NOT touch anything `ema_pullback` — Codex is actively reworking it into `rsi_dip_uptrend`; those files are in flux.
- Use `.venv/bin/python`. You are reporting facts, not making the go/no-go call (that's Claude's).

**Checks — report PASS or the specific anomaly (with numbers) for each:**

1. **Recompute headline metrics from raw ledgers.** For each strategy × {IS, OOS}, load `results/{strat}_{IS,OOS}_trades.csv` (cols: `symbol,entry_date,exit_date,entry,exit,shares,r_multiple,pct_return,exit_reason`). Compute and compare to `results/{strat}_{IS,OOS}.json`:
   - **PF three ways:** (a) dollar P&L `(exit-entry)*shares` → `sum(wins)/abs(sum(losses))`; (b) from `r_multiple` → `sum(r>0)/abs(sum(r<0))`; (c) the JSON `pf`. Report all three. If (a) differs from (c), note whether `r_multiple`/`pct_return` look net or gross of costs (the engine applies per-tier bps slippage) — don't call it a bug, just report which definition the JSON matches.
   - `n` (rows vs JSON `n`), win rate (`count(r>0)/n` vs `wr`), `avg_r` (mean `r_multiple` vs `avg_r`).
2. **Causality / lookahead (critical).** Run `.venv/bin/python -m pytest tests/ -k "donchian or high52" -q`. Then spot-check 3 traded symbols: confirm `strat.generate(df.iloc[:k])["entry_long"]` equals `strat.generate(df)["entry_long"].iloc[:k]` for a few cutoffs k. Any mismatch = lookahead = critical, flag loudly.
3. **Trade-ledger sanity.** Per strategy/split: every `exit_date >= entry_date`; no duplicate `(symbol, entry_date)`; JSON `exit_reason_counts` sums to `n`; no NaN in `entry`/`exit`/`r_multiple`.
4. **Data integrity** on the symbols these two strategies actually trade. Scan `data/1d/{symbol}.parquet`: NaNs, duplicate / non-monotonic dates, zero/negative OHLC, any single-bar move >50% (possible unadjusted split). Report counts by symbol.
5. **Penny-stock artifact (high52).** D2 noted ~25 high52 trades with entry < $5. Quantify across IS+OOS: how many trades have `entry < 5`, and what % of total `r_multiple` do they contribute? (Tells us if the edge leans on illiquid sub-$5 names.)
6. **Doc cross-check.** Confirm the donchian + high52 PF/n in `AGENT_STATUS.md` (Claude table) and `docs/REPORT_D2.md` match the JSONs. Report any mismatch.

**Output:** write findings to `docs/REPORT_AGY_verification.md` — one section per check, PASS or anomaly with numbers. Then update this AGY section with a 3-4 line summary + set Status to IDLE.

---

### Task 1 (DONE): Fix `ema_pullback` (only 15 IS trades — signal bug)

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
