# Strategy-Result Contract — v0 (normative spec)

**Current version: `0.2.0`.** Status: reviewed by Codex (consumer lane); approved with changes,
folded in here. Owned by the **engine lane** (Claude). Consumed by the **trading-copilot lane**
(Codex). Mechanical wiring + permanent tests: **AGY**.

**Artifacts in this directory**

| File | Role |
|---|---|
| `result_contract.schema.json` | Machine contract (JSON Schema, Draft 2020-12). Source of truth a consumer validates against. |
| `result_contract_v0.md` | This document. The human contract + reasoning the schema can't express. |
| `examples/orb.result.example.json` | One worked instance (orb, IS split). Validates against the schema. |
| `validate.py` | Reproducible checker: validates every example and proves all five safety guards bite. |

### Changelog

- **0.2.0** — Codex consumer-review changes + watchlist/scanner forward-compatibility:
  added `payload_type` discriminator (`backtest_result` enforced; `live_signals` **reserved**);
  `signals[].signal_id` + `trades[].source_signal_id` (journal/review linkage);
  `signals[].engine_signal_status` + `engine_skip_reason` (descriptive actionability);
  `signals[].score` (normalized 0–1, optional) + `score_name`/`score_components`;
  `strategy.live_capable` with **conditional** `required_inputs` enforcement;
  `validation_refs` (live-payload back-reference); `per_symbol_stats`;
  `data_quality` {status, flags} + `signals[].data_quality_flags`;
  `data.live_price_required_for_sizing`. Reinforced descriptive/prescriptive language.
- **0.1.0** — initial draft: descriptive engine output, point-in-time signals, sim assumptions,
  empirical risk stats, research-status gates, caveats, the engine/copilot boundary guard.

---

## 1. Purpose and scope

This contract is the **descriptive, point-in-time output of one backtest run** — and, reserved for a
future generator, a **live-signals** payload for watchlist/scanner use. It exists so a separate
copilot layer can be built against a *real, frozen target* instead of guessing.

It carries: **facts** (what ran, on what data, under what sim assumptions, what it did),
**point-in-time provenance** (enough timestamps to prove every signal is causal), **empirical risk**,
and **data-quality flags**. It carries **none** of: prescriptive risk limits, account/broker state,
credentials, dollar sizing, or execution instructions — those belong **only** to the copilot's rules
layer (§7).

**Mental model:** the engine emits *what the strategy did and what it would have you consider*; the
copilot decides *whether you're allowed to act on it*. This file is the wire between them.

---

## 2. Design principles

1. **Versioned and boring.** SemVer on the contract itself. Plain JSON, language-agnostic.
2. **Descriptive, never prescriptive.** Every field is a fact about the past or about how the
   simulation was run. Nothing authorizes a trade or sets a limit.
3. **Point-in-time first.** Every signal carries the timestamps to check no-lookahead, and all
   instants are timezone-explicit by schema rule (naive timestamps are *rejected*).
4. **Hard wall around execution and account state.** No broker, account, credential, position, or
   order — not emitted, and in v1 not even *held* by the engine. The schema rejects them (§7).
5. **Forward-ready, not forward-built.** The scanner/live direction is anticipated in the shape
   (`payload_type`, `validation_refs`, per-symbol stats, data-quality, actionability status) but only
   the `backtest_result` path is enforced and emitted in v0.2. No live generator is designed yet.

---

## 3. The descriptive / prescriptive boundary

The most important property: **one source of truth for risk policy.** The engine reports empirical
risk; the copilot owns prescriptive limits. They must not fork the same concept.

| The engine (this contract) EMITS — descriptive | The copilot (`rules.yaml`) OWNS — prescriptive |
|---|---|
| `empirical_risk_stats.*`, `per_symbol_stats.*` (what *did* happen) | `max_daily_loss`, `max_loss_per_trade`, `max_position_size` |
| `sim_assumptions.sizing_model` (`fixed_unit_R`, `dollar_sizing: not_modeled`) | actual dollar/share position sizing |
| `signals[].stop_dist` (risk *unit*, in **adjusted**-price $) | whether a trade is *permitted* now; the *live* stop in raw $ |
| `signals[].engine_signal_status` (did the engine *act*) | whether the *user* is *authorized* to act |
| `research_status`, `validation_refs` (did it pass the *research* bar) | trade *authorization* |
| `signals[].score` (descriptive ranking hint, 0–1) | "buy strength" / conviction sizing |
| `data_quality` (is the data trustworthy) | the rule that *blocks* on bad data |

**Read these reinforcements out loud — Codex flagged each as a boundary risk:**

- `sizing_model.risk_per_trade_R` is **not account sizing.** It means "the sim risked one R unit per
  trade." The copilot must **ignore it for dollar sizing** and compute real size from `rules.yaml` +
  a live quote.
- `research_status` and `validation_refs` are **never trade authorization.** They say a strategy
  cleared a *research* bar, not that *this* trade is allowed.
- `score` is **not a buy signal.** It is a normalized, strategy-defined ranking hint, null unless the
  strategy can honestly produce one. A fake score is worse than `null`.
- `stop_dist` is in **adjusted-price space** for R math only. `size_calculator.py` needs a **live raw
  quote** and a live stop reference before any real dollar size (`data.live_price_required_for_sizing`
  makes this machine-enforceable).

The copilot may **read** descriptive stats to *inform* its limits. It must never treat one as a limit.

---

## 4. The signal object — the unit shared by backtest and live

`signals[]` is **not** a trade log. It is the strategy's **decision surface**: one record per signal,
in the order the strategy would have produced them in real time.

The payoff: **a single signal object is the atomic unit a live copilot evaluates.**

```
backtest run  ->  signals[]  =  many historical signal objects
live "today"  ->  signals[]  =  one signal object for today   (payload_type: live_signals)
                              ^ identical schema
```

A live signal generator (future) emits "today's signal" in the *same shape*. The copilot's pre-trade
check is written once and works against both.

New in 0.2.0, the signal object also carries:

- **`signal_id`** — stable identity. Recommended deterministic form
  `"<strategy>:<symbol>:<bar_time>:<signal_type>"`, so the *same* signal in a backtest and live shares
  an id. `journal.csv`/`review.py` link a taken trade back to one exact signal; `trades[].source_signal_id`
  closes the loop.
- **`engine_signal_status`** — *descriptive* actionability, never authorization:
  `filled_in_backtest` / `skipped_in_backtest` / `exit_only` (backtest), or `candidate` (a fresh
  actionable live signal). `engine_skip_reason` explains a skip (`already_in_position`,
  `invalid_stop_dist`, `no_next_bar`). This lets `pre_trade_check.py` tell a real entry candidate from
  a historical signal the engine would not have acted on.
- **`score`** — optional normalized strength in `[0,1]` (+ `score_name`, `score_components`), for
  scanner ranking/throttle. `null` unless honest.

`signals[]` is *intent*; it is not the realized outcome. Not every entry signal becomes a trade.
Realized outcomes live in the optional `trades[]` ledger and aggregate into `empirical_risk_stats`
(and, for scanner use, `per_symbol_stats`).

---

## 5. Point-in-time semantics (no-lookahead)

Four instants per signal, and one invariant that makes them checkable.

| Field | Meaning | Engine source |
|---|---|---|
| `bar_time` | Label of the signal bar *t*. | `df.index[t]` |
| `data_available_at` | Instant bar *t*'s OHLC is fully observed = **bar close**. | bar *t* close instant |
| `signal_generated_at` | When the signal was computed (assume at bar close). | = `data_available_at` |
| `decision_valid_from` | Earliest actionable instant = the engine's **fill reference**. | `open[t+1]` (or `open[t]` if `entry_at_open`) |
| `decision_valid_until` | Freshness ceiling; `null` = no engine TTL, copilot owns staleness. | next decision boundary |

### The safety invariant

```
data_available_at  <=  decision_valid_from
```

> A signal may only be acted on **after** the data that produced it was knowable.
> If a result ever violates this, the signal is look-ahead-biased and the copilot **must reject it.**

### Timeline — daily bar (easy case)

```
bar t = 2024-03-05 (date label, tz-naive in engine)
        09:30 open ............................. 16:00 close
                                                   ^ data_available_at = 2024-03-05T16:00:00-05:00
   next session 2024-03-06 09:30 open
              ^ decision_valid_from = 2024-03-06T09:30:00-05:00   (clear overnight gap)
```

### Timeline — 1h bar (subtle case)

```
signal bar t labelled 10:30 (covers 10:30 -> 11:30 if START-labelled)
        10:30 open ............ 11:30 close
                                  ^ data_available_at = 11:30
   fill bar t+1 labelled 11:30:
        11:30 open ...
         ^ decision_valid_from = 11:30
```

Here `data_available_at == decision_valid_from` (both 11:30). **Correct, not a violation.** The signal
used bar *t*'s **close** price (known by 11:30); the action transacts at bar *t+1*'s **open** price
(first trade at/after 11:30). Same instant, two prices, no lookahead. The invariant is `<=`; equality
is the tight, expected case for contiguous next-open fills.

> ⚠️ **Bar-label dependency (engine-lane fact, Codex Q4).** `data_available_at` for intraday assumes
> bars are labelled by **START**. If labelled by END, it shifts one interval. Carried as a `high`
> caveat and `data_quality.flags: ["intraday_bar_label_unconfirmed"]`. Until confirmed, the copilot
> should treat intraday signals as lower-trust / block under strict rules. Confirming this is the
> engine lane's job, not a copilot design decision.

---

## 6. Field reference and engine-source mapping

The build sheet for the emitter — every field maps to a concrete engine source. (Names refer to
`src/stockslab/`.)

### Top level
| Field | Source / rule |
|---|---|
| `result_contract_version` | constant `"0.2.0"` |
| `run_id` | producer-generated, e.g. `f"{name}_{split}_{commit8}_{utcstamp}"` |
| `generated_at` | wall clock at emit, UTC `Z` |
| `repo_commit` | `git rev-parse HEAD` |
| `payload_type` | `"backtest_result"` (engine v0.2 only) |
| `validation_refs` | `null` for backtest; **required** for `live_signals` (future) |
| `per_symbol_stats` | optional: per-symbol subset of empirical stats (compute `summarize()` per symbol) |
| `data_quality` | `{status, flags}` derived from caveats/tier (see §9) |

### `strategy`
| Field | Source |
|---|---|
| `name` / `kind` / `timeframe` / `universe_label` / `params` | strategy attrs (`kind`: `signal`/`rotation`) |
| `version` | `getattr(strategy, "version", None)` — null in v0 |
| `live_capable` | `getattr(strategy, "live_capable", False)` — **default false** until confirmed; when true, every signal MUST carry non-empty `required_inputs` (schema-enforced) |
| `config.*` | `target_r, trail_atr_mult, time_stop_bars, session_exit, entry_at_open` |

### `data`
| Field | Source |
|---|---|
| `source` / `interval` / `split_label` | run params |
| `adjustment` | `"split_dividend_adjusted"` (`auto_adjust=True`) |
| `timezone` | `"America/New_York"` intraday, `"naive"` daily |
| `range.start/end` | min/max bar after `splits()` slicing |
| `live_price_required_for_sizing` | `adjustment != "raw"` → `true` |
| `bars_per_symbol` | optional `{sym: len(df)}` |

### `sim_assumptions`
Unchanged from 0.1.0 — see the table values: `engine.TIER_BPS`, `data.UNIVERSE[sym]["tier"]`,
commission `none`, fill model from the engine's frozen docstring, `fixed_unit_R` sizing,
`yfinance_native` calendar. Rotation runs: `exit_priority=["rotation","eod"]`, `stop_dist=null`,
R-proxy caveat.

### `signals[]`
| Field | Source |
|---|---|
| `signal_id` | deterministic `f"{name}:{symbol}:{bar_time_iso}:{signal_type}"` |
| `symbol` / `bar_time` / `data_available_at` / `signal_generated_at` / `decision_valid_from` / `decision_valid_until` | §5 |
| `signal_type` | `"entry"` where `entry_long[t]`, `"exit"` where `exit_long[t]` |
| `side` | `"long"` (long-only v0) |
| `engine_signal_status` | replay engine disposition: `filled_in_backtest` if it entered; `skipped_in_backtest` if `entry_long[t]` but blocked (in-position / `stop_dist` NaN≤0 / no next bar); `exit_only` for exit signals |
| `engine_skip_reason` | the blocking reason when skipped, else `null` |
| `score` / `score_name` / `score_components` | `null` unless the strategy emits an honest 0–1 score |
| `stop_dist` | `signals["stop_dist"][t]` for entries; `null` for exits |
| `required_inputs` | strategy's declared feature deps; nullable unless `live_capable` |
| `data_quality_flags` | optional per-signal flags, else `null` |

> **`engine_signal_status` derivation note.** The current engine loop does not *record* skips — it
> just doesn't enter. The emitter recomputes disposition deterministically from `(entry_long, exit_long,
> stop_dist, position state, next-bar availability)`, or the engine is lightly extended to surface a
> per-signal disposition. This is the one new field that is more than a trivial copy — see §14.

### `trades[]`
Mirrors `engine.Trade`, plus `source_signal_id` = the `signal_id` of the entry signal that produced it
(`null` if not linkable).

### `empirical_risk_stats` / `per_symbol_stats` / `research_status`
From `metrics.summarize()` + derived (unchanged mapping from 0.1.0). `per_symbol_stats[sym]` =
`summarize(trades_for_sym)` subset `{trade_count, win_rate, expectancy_R, profit_factor,
profit_factor_is_infinite}`. Gates via `metrics.phase1_gate` / `phase2_oos`.

### `caveats[]`
Standing codes: `prices_adjusted` (always), `intraday_bar_label_convention` (intraday),
`thin_intraday_history` (1h/5m), `survivorship_bias_stocks` (any stock symbol), `long_only_engine`
(always), rotation R-proxy note (rotation runs).

---

## 7. MUST NOT emit (the hard boundary)

These keys must **never** appear anywhere in a result. The schema actively rejects the top-level ones
(`validate.py` proves it), and `additionalProperties:false` rejects unknown nested keys.

- `max_daily_loss`, `max_loss_per_trade`, `max_position_size`, `account_risk_policy`, `risk_limits`
- `account_id`, `account_state`, `account_equity`, `buying_power`
- `broker`, `broker_state`, `credentials`, `api_key`
- `live_positions`, `open_positions`, `orders`
- `execution_instructions`, `order_instructions`
- any **dollar position size** (engine sizes in R units only; `dollar_sizing: not_modeled`)

**Why a hard wall, not a convention:** the engine is a research artifact. The moment it can name a
broker, an account, or a dollar size, it stops being quarantined from execution. Keeping these
un-representable means a research bug can't become a real-money side effect. This stays true for the
future `live_signals` payload — a live AMD *candidate* still carries no account/broker/execution state;
it points back to a validation run (`validation_refs`) and stops there.

---

## 8. Versioning policy

- `result_contract_version` is **SemVer for the contract**, independent of strategy or engine.
- **PATCH** (`0.2.0 → 0.2.1`): clarifications, new optional fields, new caveat/flag codes.
- **MINOR** (`0.2.x → 0.3.0`): additive but notable (e.g. enforcing the `live_signals` payload).
- **MAJOR** (`0.x → 1.0`): breaking — a required field renamed/removed/retyped, or a point-in-time
  field's meaning changed.
- The schema `$id` and the `result_contract_version` pattern are pinned to the current major.minor
  (v0.2 schema requires `^0\.2\.\d+$`). Bump both together.

---

## 9. Producer responsibilities (for whoever writes the emitter)

1. **Timezone-explicit instants, always.** Daily bars are tz-naive in the engine — *attach* the
   session timezone (render `data_available_at` as `<date>T16:00:00-05:00`/`-04:00` per DST). The
   schema **rejects** naive timestamps.
2. **Encode infinity safely.** `profit_factor: null` + `profit_factor_is_infinite: true` when PF is
   `inf`. (`phase1_gate` already treats inf PF as *suspicious*, not a pass.) Same for
   `per_symbol_stats`.
3. **Deterministic `signal_id`.** Stable across backtest and live for the same signal.
4. **Resolve, don't label.** `symbols` resolved; `slippage_model.symbol_tier` per resolved symbol.
5. **Populate `data_quality`** from known conditions: `status` = `blocked` if any `high`-severity
   data caveat that should stop trading, else `warning` if any medium, else `ok`; `flags` are stable
   keys (`adjusted_prices`, `thin_intraday_history`, `low_liquidity_tier`, `intraday_bar_label_unconfirmed`).
6. **Set `data.live_price_required_for_sizing`** true whenever prices are adjusted.
7. **Set `strategy.live_capable` honestly** (default false). If true, every signal needs non-empty
   `required_inputs`.
8. **Never compute or attach** anything from §7.

---

## 10. Resolved questions (Codex consumer review)

| # | Question | Decision |
|---|---|---|
| Q1 | `trades[]` appetite | Optional; **prefer emitting** on backtest/research runs (review.py). |
| Q2 | live single-signal envelope | **Yes, later.** Reserved now via `payload_type: live_signals` + `validation_refs`; references the historical run instead of carrying `empirical_risk_stats`. |
| Q3 | confidence/score | **Yes, optional**, normalized `[0,1]`, only when honest; `null` otherwise. |
| Q4 | bar-label convention | **Acknowledge only** — engine-lane factual confirmation. Until confirmed, intraday is lower-trust (`intraday_bar_label_unconfirmed` flag). |
| Q5 | `required_inputs` enforcement | **Required for live-capable** strategies (schema-enforced via `strategy.live_capable`). |

---

## 11. Watchlist / scanner forward-compatibility

The eventual copilot supports manual watchlists and scanner-style screening: a user enters `AMD`,
`NVDA`, `SPY`, `QQQ`, … and gets a **structured** answer — *strategy match: yes/no/waiting/blocked*,
which tested strategy, why, signal timestamp + validity window, data clean enough?, did the strategy
historically work on this symbol/universe?, would copilot rules allow it?, caveats. **Not** a
trade-calling oracle ("AMD is a buy").

This contract supplies the engine-side **ingredients** for that; the copilot computes the final
verdict. Mapping the scanner's needs to fields:

| Scanner needs | Engine provides |
|---|---|
| symbol, universe/source | `symbols`, `strategy.universe_label` |
| which strategy, its config | `strategy.name`, `strategy.params`, `strategy.config` |
| signal status (match / waiting / skipped) | `signals[].engine_signal_status` (+ copilot overlays rules) |
| signal timestamp + validity window | `signals[].bar_time` / `data_available_at` / `decision_valid_from` / `decision_valid_until` |
| why it matched / features | `signals[].required_inputs` (+ `score_components`) |
| data clean enough? | `data_quality.status/flags`, `signals[].data_quality_flags`, `data.live_price_required_for_sizing` |
| worked on THIS symbol/universe? | `per_symbol_stats[symbol]`, `research_status`, `validation_refs` |
| empirical risk | `empirical_risk_stats`, `per_symbol_stats` |
| caveats | `caveats[]` |

The verdict words the user wants — *ready / almost ready / watch only / blocked by risk / bad data /
insufficient liquidity / strategy not validated for this symbol* — are **copilot-computed** by
combining `engine_signal_status` + `data_quality` + `per_symbol_stats`/`research_status` + `rules.yaml`.
The engine never emits a verdict.

**Indexes/ETFs** (SPY/QQQ/IWM, sectors) flow through as ordinary symbols; using them for regime
context vs direct trade calls is a copilot concern. **Options** stay out of the engine entirely —
validate the underlying signal first (this contract), then a later copilot/options layer evaluates
defined-risk structures.

Implementation stays **small and engine-focused** for now: the engine keeps emitting
`backtest_result`. Batch-symbol runs already exist (`run_universe`), so per-symbol stats and a future
`live_signals` generator are additive, not a rewrite.

---

## 12. Future: `live_signals` payload (reserved, not yet emitted)

Shape, for when a live/scanner generator is built (a v0.3 concern):

```
payload_type: "live_signals"
validation_refs: [{ run_id, repo_commit, strategy_name, universe_label|symbols, split_label, research_status }]
signals: [ { ...same signal schema..., engine_signal_status: "candidate" } ]
data_quality: { ... }            # live freshness/liquidity
# NO empirical_risk_stats (it references validation_refs instead)
```

The schema already admits this (the discriminator is live and tested), but no field *requires* the
engine to produce it in v0.2. Designing the live generator is downstream work, gated on the bar-label
confirmation (Q4) for intraday.

---

## 13. Consumer checklist — what `pre_trade_check.py` does (non-normative)

This lives in the **copilot** lane; recorded here so the boundary is unambiguous. The engine does
**not** do these — it supplies the inputs. Codex's intended checks, in order:

1. Schema validates; `result_contract_version` is supported.
2. `data_available_at <= decision_valid_from`; `signal_generated_at >= data_available_at`.
3. `now` within `[decision_valid_from, decision_valid_until]` if applicable.
4. `signal_type == "entry"`; `side` allowed by `rules.yaml`.
5. `engine_signal_status` is actionable (`candidate`, not `skipped_in_backtest`).
6. `stop_dist` present and `> 0` for entries; re-derive the **live** stop from a raw quote.
7. `required_inputs` present and live-available for `live_capable` strategies.
8. No `high`-severity caveat / `data_quality.status == blocked` that `rules.yaml` says to block on.
9. `research_status` / `validation_refs` acceptable under `rules.yaml`.
10. Copilot risk limits pass (max loss/trade, daily loss, position size — all from `rules.yaml`).
11. No broker/account/execution fields present (the schema already guarantees this).

---

## 14. Next mechanical step (AGY, after the v0.2 contract is confirmed)

Settled-design, boring-but-important work. The contract is frozen at 0.2.0; build the emitter to it.

1. **Emitter.** `src/stockslab/result_contract.py` building a `backtest_result` dict from
   `(strategy, panel, trades, run metadata)` via the §6 mapping. Pure assembly **except**
   `engine_signal_status` (see the §6 derivation note — reconstruct disposition, or lightly extend the
   engine to record it). Handle the gotchas in §9 (tz-attach, PF-inf, deterministic `signal_id`,
   `data_quality`, `live_price_required_for_sizing`, default `live_capable=false`).
2. **Wire into the existing runner.** `scripts/run_backtests.py` **already exists** and today writes an
   ad-hoc `metrics.summarize()` dump + a `_trades.csv`. Emit a contract-shaped `results/<run_id>.json`
   via the emitter.
   - ⚠️ The current CSV writes `t.entry_date.isoformat()` → offset-less timestamps the schema rejects.
     The emitter must attach the session timezone.
3. **Per-symbol stats.** Populate `per_symbol_stats` by running `summarize()` per symbol (optional but
   high-value for the scanner direction).
4. **Permanent test.** Promote `contracts/validate.py` into `tests/test_result_contract.py`: schema
   valid; emitter output validates; **all five guards** bite (boundary, tz, live→inputs,
   backtest→stats, live→refs). Add `jsonschema` to dev deps.
5. **Round-trip test.** Tiny synthetic backtest → emit → validate; assert `data_available_at <=
   decision_valid_from` on every emitted signal, and that `trades[].source_signal_id` resolves to a
   real `signals[].signal_id`.

> **Coordination:** `scripts/run_backtests.py` / `scripts/robustness.py` had uncommitted edits from a
> concurrent agent when this was drafted. Rebase the emitter wiring onto whatever lands; the contract
> is independent of the runner's internals.
