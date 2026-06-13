# Harness Design Council — Findings & Decisions

**Date:** 2026-06-13
**Reviews the spec:** `docs/superpowers/specs/2026-06-13-paper-trade-harness-design.md`
**Status:** Internal council COMPLETE. External council (Codex + AGY) PENDING (Austin must launch them — they are not Hermes-dispatched; no `codex`/`agy` profile exists and the gateway is down). Spec revision is **deferred until both councils are in**, then consolidated in ONE pass (Austin's "wait, then revise once").

---

## Verdict

Internal council = 3 Sonnet critics (live-ops red-team / wall auditor / fidelity & risk-math), each verifying claims against the actual engine code. **All three returned `GO_WITH_CHANGES`, zero blocks.** The architecture and the three locked decisions (sim next-open fills / neutral-deterministic cap drop / shared `step_position` core) all held up. ~11 must-fix + ~10 should-fix issues found, several code-verified silent bugs.

## Decisions locked this session (Austin)

1. **high52 sizing = 0.5% risk/trade** (resolves spec Q1). donchian stays capped at 0.25%.
2. **No-pyramiding scope = per-(strategy, symbol)** — donchian and high52 may both hold the same symbol; each strategy tracks its own positions. Chosen for backtest fidelity (the backtest ran them independently). The per-symbol-across-strategies variant is the real-money consideration to revisit before going live.
3. **Golden-equivalence bar = exact trade-list match to full float precision** (resolves spec Q2). Bit-for-bit file hash is NOT achievable and is the wrong target. Critic 3 verified Wilder ATR computed incrementally == batch, bit-for-bit, so trade-list match IS achievable.
4. **Cap scope = donchian-only.** The 25-slot / 6.25% ceiling is donchian's; high52 is uncapped in v1 (monitored, review after paper). (Implied by the GO decision; the council flagged the §2/§7 ambiguity.)

---

## MUST-FIX (consensus / cross-critic first)

**Persist full position state in the DB — `bars_held`, `pending_exit`, `target_price`** (Critics 1, 2, 3 — strongest consensus). The harness reconstructs `step_position` state from the `positions` table each night. Two silent bugs if these aren't persisted:
- `pending_exit` not persisted → **donchian's signal exits silently never fire.** `exit_long` (Donchian-low breach) is set post-bar ([engine.py:286](../src/stockslab/engine.py:286)); if it doesn't survive the nightly boundary, branch (d) never fires and positions run past their exit until the trailing stop catches them — inflates hold time + R vs backtest.
- `bars_held` reset to 0 nightly → **gap-stop suppression becomes permanent.** Engine skips `gap_stop` only on the entry bar via `if bars_held > 0` ([engine.py:139](../src/stockslab/engine.py:139)); a daily reset means every gap-down open that should stop out is missed.
- **Fix:** add `bars_held INTEGER NOT NULL DEFAULT 0`, `pending_exit INTEGER NOT NULL DEFAULT 0`, `target_price REAL` to the `positions` table; list all of {in_position, entry_price, stop_price, stop_dist_initial, target_price, bars_held, pending_exit} in §4's state. Increment `bars_held` each day a position stays open.

**`step_position` returns price-mechanics only** (Critic 2, wall). `exit_event = (exit_date, exit_price, exit_reason)` — **no `r_multiple`/`pct_return`/`shares`**. The harness computes `r_multiple = (exit-entry)/stop_dist_initial` and `dollar_pnl = (exit-entry)*shares` from the `positions` table's real `shares`. If the engine-side `r_multiple` (computed with `n_shares=1.0`) leaks into the ledger, it's wrong for any multi-share position. Keeps the wall clean.

**`sentiment_note`/`catalyst_note` isolation must be a code contract, not a comment** (Critic 2, wall). SQLite has no column-level access control; if `ledger.py` returns full rows, every caller gets the inert columns. **Fix:** `ledger.py` exposes two query functions — `get_pending_signals_for_decision()` (SELECTs without the inert columns) and `get_signals_for_observation()` (may include them). `sizing.py`/`portfolio.py`/`fills.py`/`signals.py` may ONLY call the first. Make it a reviewable contract.

**Neutral-drop order = seeded-random keyed on `run_date`, NOT alphabetical** (Critic 2, wall). The universe has 16 A-tickers, all large-cap tech → alphabetical smuggles in a tech bias that looks like alpha over months. **Fix:** `random.Random(hash(run_date)).shuffle(pending)` — reproducible AND uncorrelated with ticker characteristics. Document the seed formula in §2 so the cap test can assert exact reproducibility.

**Data re-adjustment under open positions** (Critic 1, live-ops; my Q3 — confirmed real). [data.py:297](../src/stockslab/data.py:297) `auto_adjust=True` + full parquet overwrite → a stock split retroactively rescales all historical bars; a stored stop of 95 ends up above a market trading near 50 → phantom stop-out. No reconciliation anywhere in `src/`. **Fix:** record raw entry/stop/stop_dist + a `price_scale_factor` (default 1.0) at fill; `data_feed.py` compares cached `close[D-1]` vs freshly-fetched `close[D-1]`; if the ratio ≠ 1.0 within tolerance, a corporate action occurred → rescale open-position prices before `step_position`. (Or document a manual reconciliation runbook — but it must not stay an open question.)

**Same-bar protection for just-filled positions** (Critic 1, live-ops). §5 step 3 must update **all** open positions *including those filled in step 2 this same run*, each with `bars_held=0` (suppressing `gap_stop` on the fill bar) — mirrors the engine processing bar i+1 right after a next-open fill. Otherwise new fills skip their fill-bar stop/target check until the next run, which can't be corrected retroactively.

**Partial-run crash recovery** (Critic 1, live-ops). `run_date UNIQUE` blocks re-insert but doesn't clean up children; a crash between step 2 (fills committed) and step 3 (exit checks) drops bar D's checks silently. **Fix:** wrap steps 2–5 in a single SQLite transaction (commit only after the `runs` row writes `status=ok`; else ROLLBACK). Add `UNIQUE(strategy, symbol, signal_date)` on `signals`. Document the manual recovery path for `status=partial`.

**`signals.py` must filter same-symbol open positions before registering pending orders** (Critic 1, live-ops). `strategy.generate()` is portfolio-blind; it will return `entry_long[D]=True` for symbols already held. Per the per-(strategy,symbol) decision: skip + log `skipped_existing_position` when a position is already open for that (strategy, symbol). Distinct check from the 25-slot cap.

**`sizing.py` NaN-guards before `math.floor`** (Critic 3, fidelity). `math.floor(NaN)` raises `ValueError`, not 0. Check `stop_dist is None or isnan or <= 0` (and skip) BEFORE the division/floor — don't rely on catching a downstream exception that would abort the run.

## SHOULD-FIX

- **Remove `trail_high` from §4 state** (Critics 1 & 3) — engine trailing is ATR-anchored: `new_stop = close - trail_atr_mult*atr14; stop = max(stop, new_stop)` ([engine.py:282](../src/stockslab/engine.py:282)). No high-watermark; state is just `stop_price`. As-written it would mislead the implementer into a divergent mechanism.
- **`portfolio_timeline_summary` is batch-only** (Critic 3) — it needs completed trades (entry+exit dates) to build its sweep-line; it is NOT reusable for live cap enforcement. §3 overclaims this. Live cap = trivial counter `len(open_positions) * risk_frac`. Keep the function for post-hoc reporting only. **Also: it defaults `risk_frac=0.01` — must pass `0.0025` for donchian or open-risk numbers are 4× wrong.**
- **Cap scope wording** — state explicitly in §2/§3 that the 25 cap is donchian-only, high52 uncapped v1 (per decision 4 above).
- **Market-holiday guard** (Critic 1) — no calendar lib in the repo; running on a non-trading day crashes at `bar[D].open`. Add a trading-day guard as step 0 in `run_paper.py` (clean exit, no `runs` row) — optionally `pandas_market_calendars`.
- **Delisting per-symbol error handling** (Critic 1) — [data.py fetch raises after 3 retries](../src/stockslab/data.py); one delisted name aborts the whole ingest. Wrap each symbol's fetch in try/except, log + skip, record in `runs.notes` or a `symbol_status` table.
- **Gap-fill observability** (Critic 1) — keep unconditional next-open fill (equivalence requires it) but log `filled_gap_warning` when fill price exceeds signal-bar close by > a configurable `max_gap_pct`, to build a gap-entry-P&L dataset. Do NOT expire signals by default.
- **`signals.py` co-location / import firewall** (Critic 2) — it's descriptive but sits in `paper/` next to prescriptive modules. Either move it to `src/stockslab/` or add a forbidden-imports lint asserting `signals.py` never imports `paper.sizing|portfolio|fills`.
- **Equity-curve comparison framing** (Critic 3) — to compare paper vs backtest, regenerate the backtest curve at `risk_frac=0.0025` (not the default 1%) or compare sizing-independent per-trade R distributions. Otherwise a 4× scale mismatch reads as "divergence."
- **Editorial:** spec `[engine.py:108]` → `[engine.py:429]` (the `stop_dist_initial = sd` assignment, not the zero-init).

## Resolved open questions (from spec §11)
- **Q1** (high52 %) → 0.5% (decision 1). **Q2** (golden-equivalence bar) → exact trade-list match (decision 3). **Q3** (data re-adjustment) → must-fix above. **Q4** (open-risk ceiling) → entry-time 25×0.25% is correct conservatism; trailing only reduces live risk. **Q5/Q6** (calendar/delisting/gap) → should-fix above.

## Still open — for the EXTERNAL council
- **Codex (GPT-5.5):** the decisive question — is the `step_position` extraction actually behavior-preserving-feasible? (state threading, `atr14` precompute, `pending_exit`, `_is_last_bar_of_session`, trailing-on-close). Implementation gaps. Take on Q3/Q6.
- **AGY:** mechanical fact-check (file:line PASS/MISMATCH) of the spec's code claims + the pre-refactor test baseline (`pytest -q` count).

## Consolidation plan
When Codex + AGY report into their AGENT_STATUS sections, fold all five reviewers into ONE spec revision: apply must-fixes + accepted should-fixes, update §4/§6/§7/§9, mark §11 resolved, flip the spec status to RATIFIED → then `writing-plans` → release Codex to implement.

_Internal council raw output: workflow `wf_e27b4dfb-cc5` (3 agents, 202k tokens, 118 tool calls)._
