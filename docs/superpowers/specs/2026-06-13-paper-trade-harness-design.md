# Paper-Trade Harness — Design Spec

**Date:** 2026-06-13
**Status:** RATIFIED 2026-06-13 (Claude, engine lane). All 5 council reviewers folded in and adversarially re-verified (2 blockers + 4 majors caught and fixed in a verification workflow; see `docs/REPORT_harness_council.md`). Next: `writing-plans` → Codex implementation. Do not edit further without a new review cycle.
**Owner:** Claude (engine/research lane). Implementation: Codex. Verification: AGY.

> **Decisions locked 2026-06-13 (Austin):** (1) high52 sizing **0.5%** risk/trade (Q1 resolved). (2) No-pyramiding scope = **per-(strategy, symbol)** — both strategies may hold the same name. (3) Golden-equivalence bar = **exact trade-list match to full float precision**, not bit-for-bit (Q2 resolved). (4) The 25-slot / 6.25% cap is **donchian-only**; high52 uncapped in v1. Do not relitigate these.

> **Consolidation note (2026-06-13):** All five reviewers are now in — the internal Sonnet council (3× `GO_WITH_CHANGES`), Codex (GREEN with required changes), and AGY (mechanical fact-check, baseline = 275 passed pre-refactor). This revision folds every must-fix and accepted should-fix into one coherent pass and resolves all of §11. The earlier "consolidation deferred until the external council reports" stance is retired — it is now applied. See `docs/REPORT_harness_council.md` for the raw internal-council findings.

---

## 1. Goal & scope

Build a paper-trade harness that gives **operational proof** for the GO strategies:
signal generation, real dollar position sizing, fills, position/stop tracking, the
donchian concurrency cap, monitoring, and whether the edge behaves live-ish.

**In scope:** `donchian_breakout` + `high52_breakout` (daily-bar). `bb_squeeze_breakout`
is pluggable and joins **only if** AGY's verification battery ratifies it.

**Explicitly NOT in scope (v1):** real-money/capital deployment; broker integration
(designed-for, not built); intraday/sub-daily; any strategy off the GO path.

Both optimism discounts from the GO decision still frame everything: survivorship
(universe is 100% current survivors) and selection (survivors of a 12-strategy sweep,
no multiple-testing correction). Reported PFs are ceilings. The harness does not fix
these — but trading *forward* removes survivorship in the forward direction, which is
the one genuine epistemic upgrade paper trading provides.

## 2. Locked decisions (settled this session — not open for the council to relitigate)

These are the inputs, not the questions:

1. **Fill model:** simulated next-open fills, using the **same per-tier bps slippage**
   the backtest engine applies, behind a swappable `Fill` interface. A real broker
   (Alpaca paper) is a later swap behind the same interface, not a v1 dependency.
   Rationale: the engine *already* fills at `open[t+1]` ([engine.py:6]) — the realistic
   live convention — so daily-bar simulated next-open fills reproduce the backtest's
   fill mechanics exactly. A broker only swaps modeled prices for real ones.
2. **Concurrency-cap policy:** **neutral deterministic drop, donchian-only.** When more
   donchian entry signals fire than free slots (cap = max 25 open **donchian** positions),
   take them in a neutral order, fill to the cap, log the rest as `skipped_cap`. Per-trade
   donchian risk stays exactly 0.25%. No alpha overlay (rejected quality-ranking to keep
   the descriptive/prescriptive wall clean). Because skips are logged, we can later measure
   the edge cost of the cap vs the uncapped backtest.
   - **The neutral order is seeded-random keyed on `run_date`, NOT alphabetical** (must-fix
     M4). The universe has 16 A-tickers, all large-cap tech → an alphabetical order would
     smuggle in a tech bias that reads as alpha over months. The exact, documented seed
     formula is: `random.Random(int(run_date.replace('-', ''))).shuffle(pending)`, where
     `run_date` is the ISO date string for D (so `2026-06-13` → seed `20260613`).
     **The seed must be process-independent — do NOT use `hash(run_date)`:** CPython
     randomizes string `hash()` per process (PYTHONHASHSEED), which would make the shuffle —
     and the §9 cap test's exact filled/skipped assertion — non-deterministic across runs.
     The integer-of-the-ISO-date seed is reproducible (the cap test asserts the exact filled/
     skipped split) AND uncorrelated with ticker characteristics.
   - **Scope: the 25-slot / 6.25% cap is donchian-only** (locked decision 4). `high52` is
     **uncapped in v1** — monitored, reviewed after paper. Live cap enforcement counts only
     open *donchian* positions.
3. **Exit/stop/trail mechanics:** **extract a shared fill/exit core** (`step_position`)
   from `engine.py` that both the batch backtest and the live harness call. Single
   source of truth ⇒ live mechanics == backtest mechanics by construction. The refactor
   must be behavior-preserving (see §9). `step_position` returns **price mechanics only**
   (see §4/M2); no sizing, no `r_multiple`, no `shares`.

**Locked constraints from the ratified GO decision:**
- SQLite ledger from day one (`signals`/`trades`/`runs`/`positions`).
- donchian sizing **capped at 0.25% risk/trade, max 25 concurrent positions**
  (~6.25% open-risk ceiling). 0.5%/max-20 is a *later* test, not the start.
- high52 sizing **0.5% risk/trade, uncapped** in v1 (locked decision 4).
- Inert `sentiment_note`/`catalyst_note` field per signal: passive logging only,
  builds a future backtestable dataset, **never** an input to sizing or entries. This
  isolation is a **code contract**, not a comment (see §3/§6 and M3).
- Descriptive/prescriptive wall: the engine stays purely descriptive; the harness
  rules layer owns ALL live risk policy.

## 3. Architecture & the descriptive/prescriptive wall

```
  DESCRIPTIVE (no risk policy)            │  PRESCRIPTIVE (rules layer — all live risk)
  ──────────────────────────────────────  │  ──────────────────────────────────────────
  engine.run_signal_backtest (batch)       │  sizing.py     0.25%/0.5% risk → shares; equity model
        │  both call ▼                      │  portfolio.py  cap enforcement (donchian-only,
  engine.step_position  ◄── NEW shared      │                neutral seeded-random drop),
        ▲  core (extracted, frozen)         │                open-risk accounting
  engine.open_position_from_signal ◄ NEW    │  fills.py      Fill interface: SimFill now,
  signals.py  strategy.generate()           │                BrokerFill later (swappable)
  data_feed.py  yfinance daily refresh      │
  ───────────────────────────────────────────────────────────────────────────────────────
  OBSERVATION:  ledger.py (SQLite)  ·  monitor.py (daily summary)  ·  run_paper.py (orchestrator)
```

New code lives in a `paper/` package (proposed `src/stockslab/paper/`):
- `data_feed.py` — refresh daily bars for the universe through date D (wraps `data.py`).
  Also owns the **corporate-action re-adjustment reconciliation** (M5): compares cached
  `close[D-1]` vs freshly-fetched `close[D-1]` and, on a mismatch with factor `k`, rescales
  **all three** open-position price fields — `entry_price`, `stop_price`, AND
  `stop_dist_initial` (each `*= k`) — plus the audit `price_scale_factor`, before
  `step_position` runs. See §5 step 1.
- `signals.py` — run each strategy's `generate()` over history-to-date; emit today's
  entry/exit signals + `stop_dist`. (Descriptive — reuses verified strategy code.)
  `strategy.generate()` is **portfolio-blind**, so `signals.py` must filter same-symbol
  open positions before registering pending orders (M8).
  **S7 — co-location / import firewall:** `signals.py` is descriptive but sits in `paper/`
  next to the prescriptive modules (`sizing.py`/`portfolio.py`/`fills.py`). To stop the wall
  from silently eroding, **the chosen enforcement is a forbidden-imports lint** asserting
  `signals.py` never imports `paper.sizing`, `paper.portfolio`, or `paper.fills` (a small
  AST/grep check wired into CI). The rejected alternative was moving `signals.py` to
  `src/stockslab/` so the package boundary enforces the wall — declined because it would
  split the descriptive harness code across two packages for no extra safety the lint doesn't
  already give. Codex implements the lint, not a code comment.
- `sizing.py` — equity model + `risk_frac → shares`. **New code the backtest never had**
  (the backtest uses `n_shares = 1.0`, pure R-multiple accounting — [engine.py:112]).
  NaN-guards `stop_dist` **before** `math.floor` (M9).
- `portfolio.py` — open-position state, cap enforcement (donchian-only neutral seeded-random
  drop), open-risk accounting. Live cap is a **trivial counter** `len(open_donchian_positions)
  * risk_frac`, NOT `portfolio_timeline_summary` (which is batch-only — see S2).
- `fills.py` — the `Fill` interface; `SimFill` (next-open + slip via the shared core) now.
- `ledger.py` — SQLite read/write. Exposes **two** signal-read APIs (M3):
  `get_pending_signals_for_decision()` (SELECT *without* the inert columns) and
  `get_signals_for_observation()` (may include `sentiment_note`/`catalyst_note`). The
  decision-path modules that *consume* pending signals — `sizing.py`/`portfolio.py`/`fills.py`
  — may ONLY call the first. **`signals.py` is NOT in this list:** it is a descriptive signal
  *writer* (it calls `strategy.generate()` and INSERTs into `signals`), and its only read is
  of the `positions` table for the M8 open-position filter — it never SELECTs the inert signal
  columns, so the `get_pending_signals_for_decision()` restriction does not apply to it.
- `monitor.py` — daily summary.
- `run_paper.py` — the daily orchestrator.

**Wall placement:** engine + `signals.py` + `step_position` + `open_position_from_signal`
are descriptive (no risk policy). `sizing.py` + `portfolio.py` (cap) + `fills.py` are the
prescriptive rules layer. `ledger.py`/`monitor.py` observe. Sizing/cap logic must NOT live
in `step_position` — the engine stays risk-policy-free; the engine's `n_shares = 1.0` must
never leak into the ledger (M2).

**Inert-field isolation is a code contract, not a comment (M3).** SQLite has no
column-level access control: if `ledger.py` returned full rows, every caller would receive
the inert columns. The two-function split above (`get_pending_signals_for_decision()` vs
`get_signals_for_observation()`) makes the isolation reviewable and enforceable. The
decision-path callers physically cannot SELECT `sentiment_note`/`catalyst_note`.

**`portfolio_timeline_summary` is post-hoc reporting only (S2).** It needs *completed*
trades (entry + exit dates) to build its sweep-line, so it is NOT reusable for live cap
enforcement; the previous draft overclaimed this. Live cap enforcement is the trivial
counter above. Keep `portfolio_timeline_summary` for post-hoc reporting only, and note it
defaults `risk_frac=0.01` — callers **must pass `0.0025`** for donchian or open-risk
numbers are 4× wrong ([metrics.py:137]).

## 4. The engine refactor (`step_position` + `open_position_from_signal`)

Lift the per-bar position-update block out of `run_signal_backtest`'s loop. Two siblings
result (S9), neither carrying risk policy:

**(a) `step_position` — the in-position update core.** Extract block lives at
[engine.py:126-287] (gap_stop → stop → target → signal → time → session, final eod, then
post-bar trailing update and `pending_exit` capture).

```
step_position(state, bar, params, slip) -> (new_state, exit_event | None)
```

- `state`: **the full position state must be carried (M1).** The canonical `step_position`
  state struct is:
  `{in_position, entry_price, stop_price, stop_dist_initial, target_price, bars_held,
  pending_exit, entry_date, symbol, slippage_bps}`.
  The first seven mirror the engine's mechanics exactly ([engine.py:104-111]); the last three
  are **load-bearing for the harness** and must NOT be relegated to a parenthetical —
  `entry_date` and `symbol` are written into `positions`/`trades`, and `slippage_bps` is the
  per-tier slip threaded into every fill. `stop_dist_initial` additionally feeds downstream
  ledger `r_multiple` math. **There is no `trail_high` (S1):** engine
  trailing is ATR-anchored — `stop_price = max(stop_price, close - trail_atr_mult * atr14)`
  ([engine.py:282-284]); there is no high-watermark. State is just `stop_price`.
- `bar`: OHLC, the date/index position, the `atr14` value (for the trailing update), the
  current bar's `exit_long`, `is_final_bar`, and `is_last_bar_of_session`.
- `params`: `target_r`, `trail_atr_mult`, `time_stop_bars`, `session_exit` (read off the
  strategy).
- Returns the updated state and, if the bar closed the position, an **exit event of price
  mechanics only (M2): `exit_event = (exit_date, exit_price, exit_reason)`** where
  `exit_reason ∈ {gap_stop, stop, target, signal, time, session, eod}`. **No `r_multiple`,
  `pct_return`, or `shares`** cross the wall from the engine side — the engine's
  `n_shares = 1.0` accounting ([engine.py:112]) is wrong for any multi-share position. The
  harness ledger computes all three derived fields from the `positions` table's REAL `shares`
  (see §6/§7): `r_multiple = (exit - entry) / stop_dist_initial`,
  `pct_return = (exit - entry) / entry_price`, and `dollar_pnl = (exit - entry) * shares`.

**(b) `open_position_from_signal` — the entry-setup helper (S9).** The standard next-open
entry setup at [engine.py:423-448] should become a **separate** helper rather than being
buried in `step_position`. **Explicit signature (resolves the batch-vs-harness `entry_date`
ambiguity):**

```
open_position_from_signal(open_price, stop_dist, entry_date, params, slip) -> state
```

The helper is **context-free** — it takes the fill-bar's `open_price` and the `entry_date`
*as parameters* rather than a bar index, so it has no notion of "next bar." It sets
`entry_price = open_price*(1+slip)`, `stop_dist_initial = stop_dist`,
`stop_price = entry_price - stop_dist`,
`target_price = entry_price + params.target_r*stop_dist` (or None), the passed `entry_date`,
and `bars_held = 0` (the in-position block increments to 1 post-bar). Each caller supplies
`entry_date` from its own context:
- **Batch engine** (currently [engine.py:432]) derives it internally as `index[i+1]` and
  passes `open_price = open_[i+1]` — i.e. it threads its existing values into the helper.
- **Harness** passes `entry_date = D` and `open_price = bar[D].open` directly.

The `entry_at_open` same-bar mode at [engine.py:293-421] is **out of v1 scope** — the GO
strategies do not use it — but it stays covered by the existing engine tests (golden
equivalence, §9).

The batch engine calls these in its loop; the harness calls `step_position` once per day
per open position and `open_position_from_signal` on D-1 signals at D's open.
**The frozen check order is preserved exactly:** gap_stop → stop → target → signal → time →
session, trailing updated on close ([engine.py:8-12] and line 128). `bars_held` gates the
entry-bar gap_stop skip ([engine.py:139] — `if bars_held > 0`), which is precisely why it
must be persisted (M1).

## 5. The daily run (`run_paper.py` for date D)

Mirrors the engine "processing bar D" exactly (exit checks before the next entry; entry
from D-1's signal fills at D's open). **Two-phase write (M7):** once the step-0 trading-day
guard passes, the `runs` row is INSERTed with `status=partial` and COMMITTED *before* the
ledger-mutating work (steps 2–5), opening a real partial-row window. **Steps 2–5 then run
inside a SINGLE SQLite transaction**; that transaction's commit point is the UPDATE of the
same `runs` row to `status=ok`. If the process is killed anywhere in steps 2–5, the
transaction ROLLs BACK and the committed `runs` row is left at `status=partial`, flagging the
date for recovery.

0. **Trading-day guard (S4)** — there is no calendar lib in the repo, so running on a
   non-trading day crashes at `bar[D].open`. Check D is a trading day (optionally via
   `pandas_market_calendars`); if not, **clean exit with NO `runs` row written**.
1. **Ingest** — refresh daily bars for the universe through D. **Per-symbol fetch errors
   are caught (S5):** wrap each symbol's fetch in try/except, log + skip, record the
   outcome in `runs.notes` or a `symbol_status` table; one delisted/erroring name must not
   abort the whole ingest. **Corporate-action reconciliation (M5):** compare cached
   `close[D-1]` vs freshly-fetched `close[D-1]`; if the ratio ≠ 1.0 within tolerance, a
   corporate action occurred → with the adjustment factor `k`, rescale **all three** price
   fields on every open position BEFORE step 3: `positions.entry_price *= k`,
   `positions.stop_price *= k`, AND `positions.stop_dist_initial *= k`. Because
   `stop_dist_initial = entry_price - stop_price` pre-split, multiply it by `k` and **verify
   it equals the rescaled `entry_price - stop_price`** (a guard against drift). Multiply the
   stored `positions.price_scale_factor` by `k` for audit. Leaving `stop_dist_initial` stale
   would silently break every subsequent `r_multiple` and `sizing` calculation.
2. **Fill pending entries** — orders from D-1's signals fill at D's open `× (1+slip)`,
   via `open_position_from_signal` + `sizing.py`. **Donchian cap applied here**, against
   the live open *donchian* count: if pending donchian > free slots, take them in the
   seeded-random `run_date` order (M4), fill to the cap, log the rest `skipped_cap`. high52
   is uncapped. Size each fill via `sizing.py` (skips logged for `stop_dist ≤ 0` / `shares
   == 0`).
3. **Update open positions** — feed D's bar to `step_position` (gap_stop/stop/target/
   signal/time; trailing on D's close). **This update must iterate ALL open positions,
   including those filled in step 2 this same run (M6)** — step 3 queries
   `positions WHERE status=open` *after* step 2 has written all new fills within the same
   in-progress transaction, so the newly-filled rows are naturally visible; equivalently, keep
   an in-memory list of (pre-existing + just-filled) open positions and iterate that. Do NOT
   write step 2 and step 3 as two disjoint queries that could miss the fresh fills. Each
   newly-filled position carries `bars_held = 0` — which suppresses `gap_stop` on the fill bar
   and mirrors the engine processing bar i+1 right after a next-open fill. **Increment
   `bars_held` for every position that stays open (M1).** Exits
   → `trades` (ledger computes `r_multiple`/`pct_return`/`dollar_pnl`, M2 — see §7); slots
   freed; persist updated `bars_held`/`pending_exit`/`stop_price` back to `positions`.
4. **Generate new signals** — `strategy.generate()` over history-through-D → `entry_long[D]`
   → register pending orders to fill at **D+1's** open. **`signals.py` filters same-symbol
   open positions (M8) — post-generate:** run `strategy.generate()` first, then for any
   `(strategy, symbol)` in its output that already has an open position, **discard the signal
   before writing to the `signals` table** and log `skipped_existing_position`. (Filtering
   after generate — rather than skipping `generate()` for open symbols — is simpler and the
   wasted CPU is harmless; it never needs to know which symbols are open before running
   strategy code.) `strategy.generate()` is portfolio-blind, so this enforces the
   per-(strategy,symbol) no-pyramiding decision. This is distinct from the 25-slot cap.
   **Gap-fill observability (S6):** keep the unconditional next-open fill (equivalence
   requires it), but log `filled_gap_warning` when a fill price exceeds the signal-bar
   close by > a configurable `max_gap_pct`. Do NOT expire signals by default. Persist the
   inert sentiment/catalyst fields as NULL (passive logging populates them later, out of
   band).
5. **Persist + report** — write new `signals`, `trades`, `positions` deltas and the
   `runs` equity open/close; emit the daily monitor summary. The `runs` row already exists
   (INSERTed `status=partial` before step 2); this step's final act is the UPDATE flipping it
   to `status=ok`, which is the commit point of the M7 transaction.

**Idempotency & crash recovery (M7):** a run is keyed on `run_date` (UNIQUE); re-running a
completed date must not double-book fills or duplicate trades. `signals` additionally
carries `UNIQUE(strategy, symbol, signal_date)`. The two-phase write makes recovery
unambiguous:
- The `runs` row is INSERTed `status=partial` and committed *before* steps 2–5. This is the
  only `runs` write that lands outside the main transaction; it deliberately creates a durable
  partial-row marker.
- Steps 2–5 are one transaction whose commit point is the UPDATE to `status=ok`. A crash
  anywhere in steps 2–5 ROLLs BACK every `signals`/`trades`/`positions` delta — nothing from
  bar D is half-applied — but leaves the committed `runs` row at `status=partial`.
- **Recovery for a `status=partial` row:** because the transaction rolled back, that row has no
  committed children to clean up; recovery is simply **delete the partial `runs` row and re-run
  date D** (the `run_date` UNIQUE constraint and the `signals` UNIQUE constraint make the re-run
  idempotent even if a stray child somehow survived). A `status=partial` row that is never
  followed by a successful re-run is the durable signal that date D needs operator attention.

## 6. SQLite schema

```sql
runs(
  run_id        INTEGER PRIMARY KEY,
  run_date      TEXT UNIQUE,           -- idempotency key
  started_at    TEXT, finished_at TEXT,
  equity_open   REAL, equity_close REAL,
  status        TEXT,                  -- ok | partial | failed
  notes         TEXT                   -- per-symbol fetch outcomes / skips (S5)
)
signals(
  signal_id     INTEGER PRIMARY KEY,
  run_id        INTEGER REFERENCES runs(run_id),
  strategy      TEXT, symbol TEXT,
  signal_date   TEXT, stop_dist REAL,
  fill_target_date TEXT,
  status        TEXT,                  -- pending | filled | skipped_cap
                                       --   | skipped_existing_position | expired
  sentiment_note TEXT,                 -- INERT: write-only, no decision path reads it
  catalyst_note  TEXT,                 -- INERT
  UNIQUE(strategy, symbol, signal_date)
)
positions(
  position_id      INTEGER PRIMARY KEY,
  strategy         TEXT, symbol TEXT,
  entry_date       TEXT, entry_price REAL, shares REAL,
  stop_price       REAL, stop_dist_initial REAL,
  target_price     REAL,                  -- M1: persisted (NULL if no target)
  bars_held        INTEGER NOT NULL DEFAULT 0,   -- M1: incremented each open day
  pending_exit     INTEGER NOT NULL DEFAULT 0,   -- M1: survives the nightly boundary
  price_scale_factor REAL NOT NULL DEFAULT 1.0,  -- M5: corporate-action rescale
  status           TEXT,                  -- open | closed
  opened_run_id    INTEGER REFERENCES runs(run_id)
)
trades(
  trade_id      INTEGER PRIMARY KEY,
  position_id   INTEGER REFERENCES positions(position_id),
  strategy      TEXT, symbol TEXT,
  entry_date    TEXT, entry_price REAL,
  exit_date     TEXT, exit_price REAL, shares REAL,
  r_multiple    REAL, pct_return REAL, dollar_pnl REAL,
  exit_reason   TEXT,                  -- stop|target|signal|time|session|gap_stop|eod
  closed_run_id INTEGER REFERENCES runs(run_id)
)
```

Schema notes:
- **M1 — full position state persisted.** `target_price`, `bars_held`, and `pending_exit`
  are now columns. Without them: `pending_exit` lost across the nightly boundary →
  donchian's signal exits silently never fire. The mechanic: post-bar, `exit_long[i]` is
  *read* ([engine.py:286]) and, if true, *sets* `pending_exit = True` ([engine.py:287]) so
  the next morning's open exits on the signal; if `pending_exit` is not persisted across the
  nightly boundary, that next-morning signal-exit is silently dropped. Separately,
  `bars_held` reset to 0 nightly → the entry-bar gap_stop suppression ([engine.py:139]
  `if bars_held > 0`) becomes permanent and every gap-down open that should stop out is
  missed.
- **M5 — `price_scale_factor`** records the cumulative corporate-action rescale (default
  1.0) so raw fill/stop prices reconcile against re-adjusted yfinance history.
- **S1 — no `trail_high`.** Removed from the schema; trailing is ATR-anchored, `stop_price`
  is the only trailing state ([engine.py:282-284]).
- **M2 — engine never writes `r_multiple`/`pct_return`/`shares` into `trades`.** Those are
  computed by the harness ledger from `positions` (`shares`, `stop_dist_initial`,
  `entry_price`) and the engine's price-mechanics exit event; the engine returns price
  mechanics only. Formulas in §7.
- **M7 — `UNIQUE(strategy, symbol, signal_date)` on `signals`** plus the `run_date` UNIQUE
  on `runs` are the crash/idempotency guards.

**The wall is enforced at the code level, not just the schema (M3):** `sentiment_note`/
`catalyst_note` are written by passive logging and never SELECTed by any decision-path
module. `ledger.py` exposes `get_pending_signals_for_decision()` (no inert columns) and
`get_signals_for_observation()` (may include them); the pending-signal *consumers*
`sizing.py`/`portfolio.py`/`fills.py` may ONLY call the former. `signals.py` (a descriptive
signal writer that only reads `positions` for the M8 filter) is not a consumer and is not
subject to this restriction.

## 7. Sizing engine

```
shares = floor(risk_frac × equity / stop_dist)
```
- `stop_dist` = the strategy's initial stop distance in price terms (same quantity the
  engine normalizes `r_multiple` by — [engine.py:17]); the engine's
  `stop_dist_initial = sd` assignment is at [engine.py:429].
- donchian `risk_frac = 0.0025` (capped, donchian-only cap); high52 `risk_frac = 0.005`
  (locked decision 1; uncapped in v1).
- **NaN-guard BEFORE `math.floor` (M9):** `math.floor(NaN)` raises `ValueError`, not 0.
  Check `stop_dist is None or isnan(stop_dist) or stop_dist <= 0` and **skip** before the
  division/floor (mirrors [engine.py:18]); also skip when `shares == 0` (risk too small for
  the price) and log it. Do not rely on catching a downstream exception that would abort the
  run.
- **Equity model:** compounding on **realized** equity, **$100k** paper start. Matches the
  backtest's compounding convention — `metrics.equity_curve` / `max_dd_1pct` compounds
  realized trades by `exit_date` via `equity *= 1.0 + r_multiple * risk_frac`
  ([metrics.py:86-93]) — so live and backtest stay comparable. Open-position MTM is
  reported in the monitor but is **not** the sizing base.
- **Open-risk ceiling (donchian-only):** max 25 × 0.25% = 6.25% at entry. This is the
  *entry-time* notion of open risk (Q4-resolved): trailing stops only *reduce* live risk
  after entry, so the entry-time ceiling is the correct conservative v1 cap; monitor live
  stop distance separately. The live cap is the trivial counter
  `len(open_donchian_positions) * 0.0025`, NOT `portfolio_timeline_summary` (S2). high52 is
  uncapped in v1.

**Derived ledger fields (M2 — harness-side, not engine-side).** On exit, the harness ledger
populates the three derived `trades` columns from `positions` (real `shares`,
`stop_dist_initial`, `entry_price`) and the exit price/date returned by `step_position`:
- `r_multiple = (exit_price - entry_price) / stop_dist_initial`
- `pct_return = (exit_price - entry_price) / entry_price`
- `dollar_pnl = (exit_price - entry_price) * shares`

These mirror the engine's own formulas ([engine.py:141-142, :17]) but use REAL `shares`, so
no column is left NULL and no formula is left to implementer guesswork.

## 8. Monitoring (v1)

A daily terminal + markdown summary, persisted alongside the `runs` row: new signals,
fills, `skipped_cap` count, `skipped_existing_position` count, `filled_gap_warning` count,
open positions, open-risk vs cap (donchian only), realized P&L + open MTM, per-strategy
breakdown. A paper dashboard (reusing the `docs/dashboard_results.html` pattern) is
**deferred** to post-v1 — YAGNI for operational proof.

## 9. Testing strategy

- **Golden equivalence (the proof the refactor is safe):** the baseline is the
  **AGY-verified 275-test suite** (`pytest -q` → 275 passed pre-refactor), which must stay
  green after extracting `step_position` + `open_position_from_signal`. Golden equivalence =
  **exact trade-by-trade match** — entry/exit dates, prices, and `r_multiple` to full float
  precision — for `donchian` + high52 after the extract. (Bit-for-bit file-hash
  reproduction is the wrong target and is not achievable: CSV/JSON serialization, ordering,
  and refactor-local float-op order can drift while trade semantics stay identical. Codex
  confirmed Wilder ATR computed incrementally == batch bit-for-bit, so exact trade-list
  match IS achievable — see §11 Q2.) **Golden equivalence is tested on the BATCH path only:**
  run `run_signal_backtest` pre- and post-refactor and compare the `Trade` list — both sides
  use the engine's internal `r_multiple` computation, so this isolates the refactor. The
  harness path (which calls `step_position` directly and recomputes `r_multiple` ledger-side)
  is tested separately via the end-to-end replay test below. The `entry_at_open` mode stays
  covered by the existing engine tests even though it is out of v1 scope.
- **Sizing unit tests:** hand-computed `shares` for known equity/stop_dist/risk_frac,
  including the `stop_dist ≤ 0`, `stop_dist` NaN/None, and `shares == 0` edges (M9 — assert
  these *skip*, not raise).
- **Cap tests (M4):** 30 eligible donchian signals → exactly **25 filled / 5
  `skipped_cap`**, with the seeded-random drop order **reproducible** — the test asserts the
  exact identity of the 5 skipped names from
  `random.Random(int(run_date.replace('-', ''))).shuffle(...)`. Because the seed is the
  integer of the ISO date (not `hash(run_date)`), this assertion is stable regardless of
  PYTHONHASHSEED.
- **Same-symbol filter test (M8):** a (strategy, symbol) with an open position → a fresh
  `entry_long[D]` for it is logged `skipped_existing_position`, not registered.
- **Same-bar protection test (M6):** a position filled in step 2 is updated in step 3 with
  `bars_held = 0` and its fill-bar `gap_stop` is suppressed.
- **End-to-end replay:** drive the harness day-by-day over a historical window with the
  cap OFF → harness trades == backtest trades (ties to golden equivalence); cap ON →
  the only divergence is logged `skipped_cap` signals.
- **Idempotency / crash-recovery test (M7):** re-run a completed `run_date` → no duplicate
  trades/fills; a simulated mid-run abort ROLLs BACK with no committed children.
- **Equity-curve comparison framing (S8):** to compare paper vs backtest, regenerate the
  backtest curve at `risk_frac=0.0025` (donchian) / `0.005` (high52) — NOT the default 1% —
  OR compare sizing-independent per-trade R distributions. Otherwise a 4× scale mismatch
  reads as "divergence."

## 10. Out of scope / deferred

- Real broker / capital. (Interface designed for it; not built.)
- Intraday data or strategies.
- Paper dashboard UI.
- `entry_at_open` same-bar fill mode ([engine.py:293-421]) — out of v1 scope (GO strategies
  don't use it), but kept green by existing engine tests.
- Multiple-testing correction & walk-forward validation (separate methodology backlog —
  design-only, not blocking this harness).
- 0.5% risk / max-20 concurrency variant for donchian (a *later* test).
- Per-symbol-across-strategies no-pyramiding (the real-money consideration; v1 is
  per-(strategy, symbol)).

## 11. Resolved questions (every spec-§11 review target now closed)

1. **Q1 — high52 sizing fraction. RESOLVED → 0.5% risk/trade** (locked decision 1).
   donchian stays capped lower at 0.25% for concurrency reasons; 1% is the documented later
   test.
2. **Q2 — golden-equivalence bar. RESOLVED → exact trade-list match to full float
   precision** (locked decision 3). Bit-for-bit file-hash reproduction is the wrong target
   and not achievable (serialization/ordering/float-op-order drift). Codex confirmed the
   Wilder ATR computed incrementally equals the batch computation bit-for-bit, so
   trade-by-trade equivalence (entry/exit dates, prices, `r_multiple`) IS achievable from
   the `step_position` extract.
3. **Q3 — data re-adjustment under open positions. RESOLVED → must-fix M5** (no longer a
   note). yfinance `auto_adjust=True` + full parquet overwrite ([data.py]) means a stock
   split retroactively rescales all historical bars — a stored stop of 95 ends up above a
   market trading near 50 → phantom stop-out. Mitigation: record raw entry/stop/stop_dist +
   `price_scale_factor` (default 1.0) at fill; `data_feed.py` compares cached `close[D-1]`
   vs freshly-fetched `close[D-1]`; on a ratio ≠ 1.0 within tolerance, rescale all three
   open-position price fields (`entry_price`, `stop_price`, `stop_dist_initial`, each `*= k`)
   plus `price_scale_factor` BEFORE `step_position` (see §5 step 1).
4. **Q4 — open-risk accounting. RESOLVED → entry-time 25 × 0.25% = 6.25% is the correct v1
   ceiling.** Trailing stops only reduce live risk after entry, so the entry-time notion is
   the right conservative cap; monitor live stop distance separately.
5. **Q5 — calendar & data hazards. RESOLVED → should-fix S4 + S5.** S4: a trading-day guard
   as step 0 in `run_paper.py` (clean exit, no `runs` row; optionally
   `pandas_market_calendars`). S5: per-symbol fetch errors wrapped in try/except, logged +
   skipped, recorded in `runs.notes` / a `symbol_status` table so a single delisting can't
   abort the ingest.
6. **Q6 — pending-order lifecycle. RESOLVED → keep unconditional next-open fill** for
   backtest equivalence; log large gap fills (`filled_gap_warning`, S6); do **NOT** expire
   or revalidate pending orders in v1.
