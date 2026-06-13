# Gate Threshold Provenance

**The design-council red-team's hardest question:** were the gate thresholds —
**IS PF > 1.3, n ≥ 500, OOS PF > 1.15** — set *before* or *after* seeing
out-of-sample results? A threshold tuned to the data it later judges is circular
and would invalidate every "passed the gate" claim.

**Verdict: pre-registered and never tuned.** Evidence below.

## Timeline (git-verified)

| Artifact | Commit | Note |
|---|---|---|
| Design spec names the gate (`PF > 1.3, ≥500 trades; OOS PF > 1.15`) | `33d98aa` — **repo commit #1** | thresholds exist before any code |
| Implementation plan repeats them (`phase1_gate # pf>1.3 and n>=500`, `phase2_oos # pf>1.15`) | `3af3243` — commit #2 | — |
| Backtest engine implemented | `bd68077` | *after* the plan |
| Gate logic implemented in `metrics.py` | `ac94fdd` (Task A5) | the only commit that ever wrote these numbers |

The thresholds were written into the spec and plan **before the backtest engine
existed**, so they necessarily predate any IS or OOS result. A `git log -S`
pickaxe on each threshold expression (`pf_val > 1.3`, `n_val >= 500`,
`pf_val > 1.15`) returns **exactly one commit each — `ac94fdd` — with no later
modification.** The numbers have been immutable since first implementation; none
was moved after results came in.

## Origin of the specific numbers

- **IS PF > 1.3 and n ≥ 500** are **inherited from prior crypto/Kalshi research**,
  not invented for this project. Design spec: *"Prior crypto/Kalshi research
  established the evaluation framework: PF > 1.3, ≥500 trades, rank by PF + win
  rate; drawdown reported but not gating."* (the `mm-bot` lineage). They are
  doubly insulated from this project's results — they predate the project.
- **OOS PF > 1.15** is a deliberate **degradation haircut** off the 1.3 IS bar: it
  allows out-of-sample PF decay while still demanding profitability with margin.
  Companion robustness gates, also pre-registered: ±20% one-at-a-time param
  sensitivity must hold PF > 1.15; 2× slippage must hold PF > 1.1.

## What pre-registration does and does NOT buy us (honest caveats)

Pre-registration answers *"were the thresholds fit to the data?"* — no. It does
**not** make the numbers statistically derived or the survivors safe:

1. **The values are convention, not a power analysis.** "Established by prior
   research" is provenance, not a false-discovery-rate or minimum-detectable-effect
   calculation. 1.3 / 500 / 1.15 are reasonable, round, and inherited — not derived
   from this universe's noise level.
2. **A pre-registered gate does not fix multiple testing.** 12 strategies were run
   against one OOS window with no correction. A strategy can clear a fixed, honest
   gate by luck across 12 tries. Pre-registration and the selection problem are
   orthogonal; the latter is the open methodology-backlog item (multiple-testing
   correction + walk-forward validation).
3. **Single OOS window.** The 1.15 bar is judged on one 2022–2026 split; high52 has
   zero 2022 trades, so the bear regime is calendar-present but trade-absent for it.
4. **rsi_dip_uptrend at OOS PF 1.140 vs the 1.15 bar.** The closeness is
   uncomfortable, but the line is pre-registered and immutable, so holding it is
   principled — *not* a number chosen to exclude rsi_dip. It does show that a hard
   cutoff sitting near a realized value has thin margin, which is an argument for the
   walk-forward / multiple-testing work — not for moving the line.

**Bottom line:** the thresholds are clean on the *pre-registration* axis (the
red-team's specific question). They remain subject to the *selection* discount
already recorded in the paper-trade GO decision. Both are true at once.

---
*Written 2026-06-13 (engine lane). Resolves the "gate provenance" open item raised
by the harness design council's red-team. See `docs/REPORT_harness_council.md`.*
