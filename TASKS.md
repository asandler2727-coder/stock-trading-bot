# Tasks

## Active

- [ ] **Paper-trade go/no-go** — donchian_breakout + high52_breakout are CONFIRM; decide on launch
- [ ] **Codex: verify ema_pullback param wiring** — ema_fast/ema_mid sweeps return identical PF; check that params flow into indicator calls in `src/stockslab/strategies/ema_pullback.py`

## Waiting On

- [ ] **Codex dashboard** — `docs/dashboard_results.html` in progress (note: 5 survivors now, robustness file added for ema_pullback)

## Someday

- [ ] levered_etf_meanrev re-evaluation with longer IS window

## Done

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
