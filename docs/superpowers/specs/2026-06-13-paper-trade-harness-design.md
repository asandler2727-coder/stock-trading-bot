# Paper-Trade Harness — Design Spec

**Date:** 2026-06-13
**Status:** DRAFT — under council review (internal Claude critics + external Codex/AGY) before implementation
**Owner:** Claude (engine/research lane). Implementation: Codex. Verification: AGY.

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
2. **Concurrency-cap policy:** **neutral deterministic drop.** When more entry signals
   fire than free slots (cap = max 25 open), take them in a neutral fixed order, fill
   to the cap, log the rest as `skipped_cap`. Per-trade risk stays exactly 0.25%. No
   alpha overlay (rejected quality-ranking to keep the descriptive/prescriptive wall
   clean). Because skips are logged, we can later measure the edge cost of the cap vs
   the uncapped backtest.
3. **Exit/stop/trail mechanics:** **extract a shared fill/exit core** (`step_position`)
   from `engine.py` that both the batch backtest and the live harness call. Single
   source of truth ⇒ live mechanics == backtest mechanics by construction. The refactor
   must be behavior-preserving (see §9).

**Locked constraints from the ratified GO decision:**
- SQLite ledger from day one (`signals`/`trades`/`runs`/`positions`).
- donchian sizing **capped at 0.25% risk/trade, max 25 concurrent positions**
  (~6.25% open-risk ceiling). 0.5%/max-20 is a *later* test, not the start.
- Inert `sentiment_note`/`catalyst_note` field per signal: passive logging only,
  builds a future backtestable dataset, **never** an input to sizing or entries.
- Descriptive/prescriptive wall: the engine stays purely descriptive; the harness
  rules layer owns ALL live risk policy.

## 3. Architecture & the descriptive/prescriptive wall

```
  DESCRIPTIVE (no risk policy)            │  PRESCRIPTIVE (rules layer — all live risk)
  ──────────────────────────────────────  │  ──────────────────────────────────────────
  engine.run_signal_backtest (batch)       │  sizing.py     0.25% risk → shares; equity model
        │  both call ▼                      │  portfolio.py  cap enforcement (neutral drop),
  engine.step_position  ◄── NEW shared      │                open-risk accounting
        ▲  core (extracted, frozen)         │  fills.py      Fill interface: SimFill now,
  signals.py  strategy.generate()           │                BrokerFill later (swappable)
  data_feed.py  yfinance daily refresh      │
  ───────────────────────────────────────────────────────────────────────────────────────
  OBSERVATION:  ledger.py (SQLite)  ·  monitor.py (daily summary)  ·  run_paper.py (orchestrator)
```

New code lives in a `paper/` package (proposed `src/stockslab/paper/`):
- `data_feed.py` — refresh daily bars for the universe through date D (wraps `data.py`).
- `signals.py` — run each strategy's `generate()` over history-to-date; emit today's
  entry/exit signals + `stop_dist`. (Descriptive — reuses verified strategy code.)
- `sizing.py` — equity model + `0.25% risk → shares`. **New code the backtest never had**
  (the backtest uses `n_shares = 1.0`, pure R-multiple accounting — [engine.py:112]).
- `portfolio.py` — open-position state, cap enforcement (neutral drop), open-risk
  accounting (reuses the concurrency logic from `scripts/portfolio_view.py` / `metrics.py`).
- `fills.py` — the `Fill` interface; `SimFill` (next-open + slip via the shared core) now.
- `ledger.py` — SQLite read/write.
- `monitor.py` — daily summary.
- `run_paper.py` — the daily orchestrator.

**Wall placement:** engine + `signals.py` + `step_position` are descriptive (no risk
policy). `sizing.py` + `portfolio.py` (cap) + `fills.py` are the prescriptive rules
layer. `ledger.py`/`monitor.py` observe. Sizing/cap logic must NOT live in
`step_position` — the engine stays risk-policy-free.

## 4. The engine refactor (`step_position`)

Lift the per-bar position-update block out of `run_signal_backtest`'s loop
([engine.py:120+]) into:

```
step_position(state, bar, params, slip) -> (new_state, exit_event | None)
```

- `state`: in_position, entry_price, stop_price, stop_dist_initial, target_price,
  trail_high/atr context, bars_held.
- `bar`: one row of OHLC (+ the atr14 value for the trailing update).
- `params`: target_r, trail_atr_mult, time_stop_bars, session_exit (read off the strategy).
- Returns the updated state and, if the bar closed the position, an exit event
  (date, price, reason ∈ {gap_stop, stop, target, signal, time, session, eod}).

The batch engine calls it in its loop; the harness calls it once per day per open
position. **The frozen check order is preserved exactly:** gap_stop → stop → target →
signal → time → session, trailing updated on close ([engine.py:5-16]).

## 5. The daily run (`run_paper.py` for date D)

Mirrors the engine "processing bar D" exactly (exit checks before the next entry; entry
from D-1's signal fills at D's open):

1. **Ingest** — refresh daily bars for the universe through D.
2. **Fill pending entries** — orders from D-1's signals fill at D's open `× (1+slip)`.
   **Cap applied here**, against the live open count: if pending > free slots,
   neutral-deterministic order, fill to the cap, log the rest `skipped_cap`. Size each
   fill via `sizing.py`.
3. **Update open positions** — feed D's bar to `step_position` (gap_stop/stop/target/
   signal/time; trailing on D's close). Exits → `trades`; slots freed.
4. **Generate new signals** — `strategy.generate()` over history-through-D → `entry_long[D]`
   → register pending orders to fill at **D+1's** open. Persist the inert
   sentiment/catalyst fields as NULL (passive logging populates them later, out of band).
5. **Persist + report** — write the `runs` row (equity open/close, status), new `signals`,
   `trades`, `positions` deltas; emit the daily monitor summary.

Idempotency: a run is keyed on `run_date`; re-running a completed date must not
double-book fills or duplicate trades (see §6 + open question Q3).

## 6. SQLite schema

```sql
runs(
  run_id        INTEGER PRIMARY KEY,
  run_date      TEXT UNIQUE,           -- idempotency key
  started_at    TEXT, finished_at TEXT,
  equity_open   REAL, equity_close REAL,
  status        TEXT,                  -- ok | partial | failed
  notes         TEXT
)
signals(
  signal_id     INTEGER PRIMARY KEY,
  run_id        INTEGER REFERENCES runs(run_id),
  strategy      TEXT, symbol TEXT,
  signal_date   TEXT, stop_dist REAL,
  fill_target_date TEXT,
  status        TEXT,                  -- pending | filled | skipped_cap | expired
  sentiment_note TEXT,                 -- INERT: write-only, no decision path reads it
  catalyst_note  TEXT                  -- INERT
)
positions(
  position_id   INTEGER PRIMARY KEY,
  strategy      TEXT, symbol TEXT,
  entry_date    TEXT, entry_price REAL, shares REAL,
  stop_price    REAL, stop_dist_initial REAL, trail_high REAL,
  status        TEXT,                  -- open | closed
  opened_run_id INTEGER REFERENCES runs(run_id)
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

The wall is enforced at the schema level: `sentiment_note`/`catalyst_note` are written
by passive logging and never SELECTed by `sizing.py`/`portfolio.py`/`fills.py`/`signals.py`.

## 7. Sizing engine

```
shares = floor(risk_frac × equity / stop_dist)
```
- `stop_dist` = the strategy's initial stop distance in price terms (same quantity the
  engine normalizes `r_multiple` by — [engine.py:17], [engine.py:108]).
- donchian `risk_frac = 0.0025` (capped); high52 `risk_frac = 0.005` *(default — see Q1)*.
- Skip the entry when `stop_dist` is NaN or ≤ 0 (mirrors [engine.py:18]); skip when
  `shares == 0` (risk too small for the price) and log it.
- **Equity model:** compounding on **realized** equity, **$100k** paper start. Matches the
  backtest's compounding convention (`metrics.equity_curve` compounds realized trades by
  exit date) so live and backtest stay comparable. Open-position MTM is reported in the
  monitor but is **not** the sizing base.
- **Open-risk ceiling:** max 25 × 0.25% = 6.25% at entry. This is the *entry-time* notion
  of open risk (see Q4 — live risk drifts as trailing stops tighten; the cap governs entry).

## 8. Monitoring (v1)

A daily terminal + markdown summary, persisted alongside the `runs` row: new signals,
fills, `skipped_cap` count, open positions, open-risk vs cap, realized P&L + open MTM,
per-strategy breakdown. A paper dashboard (reusing the `docs/dashboard_results.html`
pattern) is **deferred** to post-v1 — YAGNI for operational proof.

## 9. Testing strategy

- **Golden equivalence (the proof the refactor is safe):** after extracting
  `step_position`, regenerating the backtest must reproduce the current trade ledgers
  for donchian + high52 — exact trade-by-trade match (entry/exit dates, prices, r_multiple
  to full float precision). The full 275-test suite stays green. *(Open question Q2:
  is "bit-for-bit" the right bar, or "exact trade-list match"? See §11.)*
- **Sizing unit tests:** hand-computed `shares` for known equity/stop_dist/risk_frac,
  including the `stop_dist ≤ 0` and `shares == 0` edges.
- **Cap tests:** 30 simultaneous eligible signals → exactly 25 filled, 5 `skipped_cap`,
  deterministic which 5 (the neutral order is reproducible).
- **End-to-end replay:** drive the harness day-by-day over a historical window with the
  cap OFF → harness trades == backtest trades (ties to golden equivalence); cap ON →
  the only divergence is logged `skipped_cap` signals.
- **Idempotency test:** re-run a completed `run_date` → no duplicate trades/fills.

## 10. Out of scope / deferred

- Real broker / capital. (Interface designed for it; not built.)
- Intraday data or strategies.
- Paper dashboard UI.
- Multiple-testing correction & walk-forward validation (separate methodology backlog —
  design-only, not blocking this harness).
- 0.5% risk / max-20 concurrency variant for donchian (a *later* test).

## 11. Open questions / review targets (the council's job)

1. **Q1 — high52 sizing fraction.** Default set to 0.5% risk/trade (conservative middle:
   donchian is capped lower at 0.25% for concurrency reasons; 1% is the documented later
   test). **Austin to confirm 0.5% vs 1%.**
2. **Q2 — golden-equivalence bar.** Is "bit-for-bit" file-hash reproduction achievable
   from a `step_position` extract (float-op ordering, atr recompute, vectorization), or
   should the equivalence bar be "exact trade-list match to full float precision"? Which
   is both *sufficient* and *achievable*?
3. **Q3 — data re-adjustment under open positions.** yfinance auto-adjusts; re-pulling
   daily history could retroactively shift the prices of bars an open position was entered
   on. Does this corrupt live position state / stop levels? Mitigation needed?
4. **Q4 — open-risk accounting.** Is "25 × 0.25% = 6.25%" the right ceiling notion given
   trailing stops change live risk after entry, or should the cap track live stop distance?
5. **Q5 — calendar & data hazards.** Holidays (no bar for D), missing/late yfinance data,
   mid-position splits, delistings of a universe symbol mid-run.
6. **Q6 — pending-order lifecycle.** A signal fires on D, fills at D+1 open
   unconditionally (engine convention). Is unconditional next-open fill correct for live,
   or should a pending order be re-validated / expired?
```
