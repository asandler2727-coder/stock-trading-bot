# Tasks

## Active

- [ ] **Build paper-trade harness** — donchian_breakout + high52_breakout APPROVED GO (2026-06-12); greenfield: position sizing (donchian wants ≤0.5% risk — 71.6% max DD at 1%), result-contract wiring, monitoring
- [ ] **AGY: independent verification battery** (donchian + high52) — read-only; recompute PF/n/wr from raw trade ledgers, causality + data-integrity + penny-stock checks → `docs/REPORT_AGY_verification.md` (running)

## Someday

- [ ] levered_etf_meanrev re-evaluation with longer IS window
- [ ] xsec_momentum fixes (off-by-one momentum index, Monday-holiday rebalance) — only if promoted; needs regime/sizing first

## Done

- [x] ~~Paper-trade go/no-go~~ (2026-06-12) — APPROVED GO: donchian_breakout + high52_breakout (spec-clean, robust IS+OOS+2× slippage)
- [x] ~~Diagnose ema_pullback param mystery~~ (2026-06-12) — NOT a wiring bug; spec drift (pullback + ema50>ema200 conditions inert after AGY's fix); Austin chose accept-as-RSI-dip
- [x] ~~Codex strategy spec review (5 gate passers)~~ (2026-06-12) — donchian/high52 clean; ema_pullback drift confirmed + vacuous test found; xsec bugs confirmed
- [x] ~~Codex build results dashboard~~ (2026-06-12) — docs/dashboard_results.html (12 rows: gate table, equity, exits, robustness)
- [x] ~~Confirm intraday bar-label convention (Q4)~~ (2026-06-12) — BAR-START; 09:30 = open time
- [x] ~~Commit contracts/~~ (2026-06-12) — committed 121eb96
- [x] ~~Build strategy 11: vwap_reclaim~~ (2026-06-12) — committed 9808cb9
- [x] ~~Build strategy 12: intraday_momentum~~ (2026-06-12) — committed 5b5ec43
- [x] ~~Draft result contract v0.2.0~~ (2026-06-12) — committed 121eb96
- [x] ~~Codex confirm v0.2.0~~ (2026-06-12) — signed off, 3 judgment calls accepted
- [x] ~~AGY build result emitter~~ (2026-06-12) — committed 9774a2b + 443432c + b367efe
- [x] ~~Phase D Kanban audits~~ (2026-06-12) — D1 (4 strategies) + D2 synthesis done; report at docs/REPORT_D2.md
- [x] ~~AGY fix ema_pullback bug~~ (2026-06-12) — fixed close>ema50 condition; new IS n=5423 PF=1.387
- [x] ~~AGY investigate levered_etf_meanrev anomaly~~ (2026-06-12) — QQQ filter confirmed working; IS bad years (2018/2019) explain gap
- [x] ~~Robustness sweep for ema_pullback~~ (2026-06-12) — results/robustness_ema_pullback.json; REVIEW verdict
- [x] ~~Codex: ema_pullback → RSI-dip rework~~ (2026-06-12) — renamed `rsi_dip_uptrend`; IS PF=1.387247/N=5423; OOS PF=1.290191/N=1649; tests green
- [x] ~~Claude: verify rsi_dip_uptrend rework~~ (2026-06-12) — independent rerun: IS 1.3872/5423 (exact), OOS 1.2902/1649 (holds), 262 tests green, rename clean repo-wide
