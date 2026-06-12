# Two-Track Stock Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a TDD'd backtest lab and evaluate 12 swing/day-trade stock strategies against the gate (IS PF>1.3, ≥500 trades; OOS PF>1.15; sensitivity ±20%; 2× cost stress).

**Architecture:** Standalone Python package `stockslab` under `src/`. yfinance→parquet data layer; per-symbol event-loop backtest engine with strict anti-lookahead semantics; strategies as plug-in files auto-discovered by a registry; metrics/gate module; scripts to fetch, run, and report.

**Tech Stack:** Python 3.14, pandas 3.x, numpy, pyarrow, yfinance, pytest. No TA-Lib (indicators hand-rolled in `indicators.py`). No freqtrade, no vectorbt.

**Spec:** `docs/superpowers/specs/2026-06-12-two-track-stock-research-design.md` — engine semantics there are normative.

---

## Frozen API contract (all tasks build against this — do not deviate)

### Data schema
Per-symbol `pd.DataFrame`: index `DatetimeIndex` named `date` (daily: tz-naive; intraday: tz `America/New_York`), columns exactly `open, high, low, close, volume` (float64, lowercase), auto-adjusted prices, strictly increasing index, no NaN rows.

### Strategy interfaces (`src/stockslab/strategies/base.py`)

```python
from dataclasses import dataclass, field
import pandas as pd

@dataclass
class SignalStrategy:
    """Signal-based strategy. Engine semantics:
    - entry_long[t] True  -> enter at open[t+1] (unless entry_at_open, see gap_fade)
    - exit_long[t]  True  -> exit  at open[t+1]
    - stop_dist[t] ($ distance) defines initial stop at entry; R = pnl / stop_dist
    - target_r (R multiple) optional profit target; trail_atr_mult optional trailing stop
    - time_stop_bars optional max holding period
    - session_exit: intraday only — force exit at last bar of session close
    """
    name: str = "base"
    params: dict = field(default_factory=dict)
    timeframe: str = "1d"            # "1d" | "1h" | "5m"
    universe: str = "all"            # "all" | "stocks" | "etfs" | "levered"
    target_r: float | None = None
    trail_atr_mult: float | None = None
    time_stop_bars: int | None = None
    session_exit: bool = False
    entry_at_open: bool = False      # gap_fade only: entry signal uses bar t open, fills bar t open

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return DataFrame indexed like df with columns:
        entry_long (bool), exit_long (bool), stop_dist (float, NaN when no entry).
        MUST be causal: row t uses data up to and including bar t close
        (or ONLY bar t open if entry_at_open).
        """
        raise NotImplementedError

@dataclass
class RotationStrategy:
    """Rebalance to equal-weight target list at each rebalance close; fills next open."""
    name: str = "base_rotation"
    params: dict = field(default_factory=dict)
    timeframe: str = "1d"
    universe: str = "all"

    def target_holdings(self, panel: dict[str, pd.DataFrame], dates: pd.DatetimeIndex) -> pd.DataFrame:
        """Return DataFrame index=rebalance dates (subset of dates), columns=symbols,
        values 0/1 membership. Row at date d may use data up to and including d close."""
        raise NotImplementedError

REGISTRY: dict[str, object] = {}

def register(cls):
    inst = cls()
    REGISTRY[inst.name] = inst
    return cls
```

### Engine (`src/stockslab/engine.py`)

```python
@dataclass
class Trade:
    symbol: str; entry_date: pd.Timestamp; exit_date: pd.Timestamp
    entry: float; exit: float; shares: float
    r_multiple: float          # (exit-entry)/stop_dist_initial, slippage included
    pct_return: float          # (exit-entry)/entry, slippage included
    exit_reason: str           # "stop"|"target"|"signal"|"time"|"session"|"gap_stop"|"eod"

def run_signal_backtest(strategy, df, symbol, slippage_bps) -> list[Trade]: ...
def run_rotation_backtest(strategy, panel, slippage_bps_map) -> list[Trade]: ...
def run_universe(strategy, panel: dict[str, pd.DataFrame], tiers: dict[str, int]) -> list[Trade]: ...
```

Semantics (each is an engine test):
1. Entry at `open[t+1] * (1 + slip)` when `entry_long[t]`; slip = bps/10_000.
2. In-position bar check order: (a) `open <= stop` → exit at open (`gap_stop`); (b) `low <= stop` → exit at stop (`stop`); (c) target set and `high >= target` → exit at target (`target`); stop checked before target always. (d) `exit_long[t-1]` → exit at `open[t]` (`signal`); (e) time stop expiry → exit at `open[t]` (`time`).
3. Trailing: after bar t close, `stop = max(stop, close[t] - trail_atr_mult * atr14[t])` (engine computes atr14 itself).
4. Exit fills get `* (1 - slip)`. Position still open at final bar → exit last close (`eod`).
5. One position per symbol; no pyramiding. `entry_at_open`: `entry_long[t]` fills at `open[t] * (1+slip)` same bar; with `session_exit`/same-close exits as given by exit columns.
6. Slippage tiers (per side, bps): `TIER_BPS = {1: 1, 2: 3, 3: 5}` — tier map in `data.py:UNIVERSE` (major ETFs 1, megacaps 2, rest+levered 3).

### Metrics (`src/stockslab/metrics.py`)

```python
def profit_factor(trades) -> float        # sum(R>0)/abs(sum(R<0)) on r_multiple; inf-safe
def win_rate(trades) -> float
def summarize(trades) -> dict             # pf, wr, n, avg_r, med_hold_bars, max_dd_1pct, exit_reason_counts
def equity_curve(trades, risk_frac=0.01) -> pd.Series   # date-ordered compounding by r_multiple*risk_frac
def max_drawdown(curve) -> float
def phase1_gate(s: dict) -> tuple[bool, list[str]]      # pf>1.3 and n>=500
def phase2_oos(s: dict) -> tuple[bool, list[str]]       # pf>1.15
```

### Data (`src/stockslab/data.py`)

```python
UNIVERSE: dict[str, dict]   # symbol -> {"kind": "etf"|"levered"|"stock", "tier": 1|2|3}
def fetch(symbol, interval, start=None, force=False) -> pd.DataFrame   # yfinance + parquet cache in data/{interval}/{symbol}.parquet, 3-try backoff, validates schema
def load_panel(symbols, interval, start=None) -> dict[str, pd.DataFrame]  # cache-only read
def splits(interval) -> tuple[slice, slice]  # IS/OOS date slices per spec
```

---

## Phase A — Infrastructure

### Task A1: Scaffold

**Files:** Create `pyproject.toml`, `.gitignore`, `requirements.txt`, `src/stockslab/__init__.py`, `src/stockslab/strategies/__init__.py`, `tests/__init__.py`, `conftest.py`

- [ ] Step 1: `python3 -m venv .venv && .venv/bin/pip install -U pip`
- [ ] Step 2: `requirements.txt`: `pandas>=3.0\nnumpy\npyarrow\nyfinance>=0.2.50\npytest\nmatplotlib`; install: `.venv/bin/pip install -r requirements.txt`
- [ ] Step 3: `pyproject.toml` minimal setuptools package (`packages = ["stockslab"]`, `package-dir = {"" = "src"}`); `.venv/bin/pip install -e .`
- [ ] Step 4: `.gitignore`: `.venv/`, `data/`, `results/`, `__pycache__/`, `*.pyc`
- [ ] Step 5: smoke test `tests/test_smoke.py::test_import` → `import stockslab`; run `.venv/bin/pytest -q` → 1 passed
- [ ] Step 6: Commit `chore: scaffold stockslab package`

### Task A2: Indicators (TDD against hand-computed values)

**Files:** Create `src/stockslab/indicators.py`, `tests/test_indicators.py`

Functions: `sma, ema, rsi(wilder), atr(wilder, n=14), donchian_high(n), donchian_low(n), bb(n, k) -> (mid, upper, lower, width), rolling_zscore(n), session_vwap(df)` — all return Series aligned to input, NaN until warm-up, **no future leakage** (rolling windows end at current row).

- [ ] Step 1: Write failing tests with hand-computed references, e.g.:

```python
def test_sma_basic():
    s = pd.Series([1, 2, 3, 4, 5], dtype=float)
    assert indicators.sma(s, 3).tolist()[2:] == [2.0, 3.0, 4.0]

def test_rsi_wilder_known_value():
    # 14-period Wilder RSI on the classic Wilder dataset; assert round(rsi.iloc[14],2) == 70.46
def test_atr_wilder_simple():
    # constant TR=1 series -> atr converges to 1.0
def test_no_lookahead_all_indicators():
    # for each indicator: compute on full series and on series[:k]; values up to k-1 must match
def test_session_vwap_resets_daily():
    # two synthetic sessions; vwap of first bar of day 2 == typical price of that bar
```

- [ ] Step 2: Run → fail. Step 3: implement. Step 4: pass. Step 5: commit `feat: indicators with anti-lookahead tests`

### Task A3: Data layer

**Files:** Create `src/stockslab/data.py`, `scripts/fetch_data.py`, `tests/test_data.py`

- [ ] Step 1: failing tests — schema validation (`validate(df)` raises on NaN rows / non-monotonic index / missing cols), cache round-trip via tmp_path monkeypatched cache dir, `splits("1d") == (slice("2010-01-01","2021-12-31"), slice("2022-01-01","2026-06-01"))`, UNIVERSE contains the spec's ETF list with correct tiers.
- [ ] Step 2: implement `data.py`. UNIVERSE: ETFs/levered per spec; stocks = current S&P 100 + AMD, PLTR, COIN, MSTR, SMCI, SNOW, NET, SHOP, SQ, ROKU, DKNG, RIVN, SOFI, HOOD, MARA, RIOT, CLF, AA, OXY, DVN, FCX, ENPH, U, RBLX, ABNB, DASH, UBER, LYFT, ZM, CRWD (30 liquid/high-beta).
- [ ] Step 3: `scripts/fetch_data.py --interval 1d|1h|5m [--symbols ...]` → fetches with 1.5s sleep between calls, 3-retry exponential backoff, prints summary table (symbol, rows, first/last date). Daily start=2000-01-01; 1h period=730d; 5m period=60d.
- [ ] Step 4: tests pass; commit `feat: data layer with parquet cache and universe`

### Task A4: Signal engine (the correctness core)

**Files:** Create `src/stockslab/engine.py`, `tests/test_engine.py`

- [ ] Step 1: failing tests — one per semantic rule, on tiny hand-built OHLC frames where every fill price is computed by hand in the test, including:

```python
def test_entry_next_open_with_slippage():      # signal bar t -> fill open[t+1]*(1+0.0003) for tier 2
def test_stop_hit_intrabar_fills_at_stop():
def test_gap_through_stop_fills_at_open():
def test_stop_checked_before_target_same_bar():
def test_target_hit_fills_at_target():
def test_exit_signal_fills_next_open():
def test_time_stop_exits_after_n_bars():
def test_trailing_stop_ratchets_up_never_down():
def test_no_pyramiding_second_signal_ignored_while_open():
def test_open_position_closed_at_final_bar():
def test_r_multiple_accounting_includes_slippage():
def test_entry_at_open_same_bar_fill():
def test_session_exit_last_bar_of_day():        # intraday index
def test_no_entry_when_stop_dist_nan_or_zero():
```

- [ ] Step 2: run → fail. Step 3: implement per-symbol loop engine exactly per the contract. Step 4: pass. Step 5: commit `feat: signal engine with full semantics test suite`

### Task A5: Rotation engine + metrics

**Files:** Modify `src/stockslab/engine.py`; create `src/stockslab/metrics.py`, `tests/test_rotation.py`, `tests/test_metrics.py`

- [ ] Step 1: failing tests — rotation: membership change at rebalance d fills at next open for both adds and drops; held-through positions untouched; each add = one Trade with pct_return; r_multiple for rotation trades = pct_return / 0.10 (notional 10%-move R proxy, documented). Metrics: PF/WR on hand-built trade lists; PF inf-safe (no losses → inf, gate handles); equity curve compounding order = exit_date sort; gates return reason strings.
- [ ] Step 2-5: implement, pass, commit `feat: rotation engine and metrics/gates`

### Task A6 (gate): Adversarial engine review — Opus

Dispatch 2 independent Opus reviewers against `engine.py`+tests: hunt lookahead bias, off-by-one on signal shifting, fill-price errors, R-accounting errors. Findings fixed + re-tested before Phase B. No strategy work may start until both reviewers return no-critical-findings.

---

## Phase B — Strategies (12 parallel tasks, disjoint files)

> **Sizing scope (Phase B–C):** Gate evaluation uses R-multiples only (`profit_factor`, `win_rate`, `n`). Fixed-fraction dollar sizing, floored shares, concurrent-position caps, and portfolio heat are intentionally out of scope for the gate — R-multiples are sizing-independent and sufficient to rank strategies. The `equity_curve(risk_frac=0.01)` function approximates the 1%-risk compounded curve correctly for drawdown reporting. Full position-sizing and heat-cap enforcement is a Phase D+ live-trading concern.

Every strategy: create `src/stockslab/strategies/<name>.py` + `tests/test_strat_<name>.py`. Each must `@register`, set `timeframe`/`universe`, and pass: (a) causality test — `generate(df[:k])` rows match `generate(df)` rows up to k-1 on random synthetic OHLC; (b) at least one synthetic-scenario test proving entries fire exactly when rules say. Commit per strategy: `feat: strategy <name>`.

Exact rules (params in `self.params`, defaults shown — these are the ±20% sensitivity knobs):

1. **donchian_breakout** (1d, all): entry when `close > donchian_high(55).shift(1)`; stop_dist `2*atr(14)`; trail_atr_mult 3; exit when `close < donchian_low(20).shift(1)`.
2. **rsi_dip_uptrend** (1d, all): uptrend `close > ema200`; entry when uptrend and `rsi(14) < 40`; stop_dist `1.5*atr(14)`; target_r 2.0; time_stop_bars 15.
3. **rsi2_meanrev** (1d, stocks+SPY/QQQ): entry `close>sma200 and rsi(2)<10`; exit `rsi(2)>70 or close>sma5`; stop_dist `2.5*atr(14)`; time_stop_bars 10.
4. **bb_squeeze_breakout** (1d, all): squeeze = `bb_width(20,2)` in lowest 15th pctile of trailing 252; entry when squeeze yesterday and `close>bb_upper`; stop_dist `2*atr(14)`; trail 2.5.
5. **xsec_momentum** (1d rotation, stocks): every Monday, rank by `close.shift(21)/close.shift(252)-1` (12-1 momentum), hold top 10; only when SPY>sma200 else empty.
6. **sector_rotation** (1d rotation, 11 sector ETFs): weekly top 3 by mean of 1/3/6-month returns; only when SPY>sma200.
7. **gap_fade** (1d, stocks, entry_at_open): yesterday uptrend (`close>sma50`); today `open < prev_close*0.98` and `open > prev_close*0.90`; enter at open; exit same close (exit_long same bar — engine: entry_at_open + time_stop_bars=1 semantics, exit at that bar's close, reason "time"); stop_dist `prev_close*0.05`.
8. **levered_etf_meanrev** (1d, TQQQ/SOXL/UPRO/TNA): entry `QQQ.close>QQQ.sma200` (cross-frame: strategy takes spy/qqq context via `prepare_context(panel)` hook, see base note) and `rsi(2)<10` on the levered ETF; exit `rsi(2)>65`; stop_dist `3*atr(14)`; time_stop_bars 10.
9. **high52_breakout** (1d, stocks): entry `high >= rolling_max(high,252).shift(1) and volume > 1.5*sma(volume,50)`; stop_dist `2*atr(14)`; trail 3.
10. **orb** (1h, SPY/QQQ/TQQQ + stocks tier≤2): first bar of session defines range; entry when a later bar closes above range high; stop_dist = range size; session_exit True; target_r 2.
11. **vwap_reclaim** (1h, stocks tier≤2): entry when `close` crosses above `session_vwap` from below and prior bar fully below vwap, and day's first bar was red; stop_dist `1*atr(14)`; session_exit True; target_r 1.5.
12. **intraday_momentum** (1h, SPY/QQQ): if return from session open to 12:30 bar close > +0.3%, enter; session_exit True (last-hour momentum continuation); stop_dist `1*atr(14)`.

Note for 8: add optional `context: dict[str, pd.DataFrame]` attribute on SignalStrategy; `run_universe` sets `strategy.context = panel` before per-symbol runs. Causality contract applies to context frames too.

---

## Phase C — Runner & robustness

### Task C1: `scripts/run_backtests.py`
For each registered strategy: load panel for its timeframe/universe, slice IS, run, `summarize`, write `results/{strategy}_{IS|OOS}.json` + trades CSV; print gate table. Flags: `--strategies`, `--split IS|OOS|full`, `--slippage-mult`. Test: end-to-end on 2 synthetic symbols with a stub strategy.

### Task C2: `scripts/robustness.py`
For gate survivors: rerun IS with each numeric param at 0.8× and 1.2× (one-at-a-time), and 2× slippage; write `results/robustness_{strategy}.json` (param, value, pf, n). Pass criteria per spec.

### Task C3: `scripts/make_report.py`
Render `docs/REPORT.md`: ranked table (strategy, track, IS pf/wr/n, OOS pf/wr/n, maxDD@1%, sensitivity min-PF, 2×cost PF, verdict), per-strategy sections, caveats block (survivorship, thin intraday, regime).

---

## Phase D — Verification & synthesis (Opus)

- D1: 2–3 Opus auditors per *surviving* strategy: independently recompute PF from the trades CSV, hunt for data artifacts (splits, halts, penny fills), check trade distribution isn't concentrated in a handful of symbols/months, verify the strategy logic matches its spec rule. Verdict: confirm/refute with reasons.
- D2: 1 Opus synthesis agent: final REPORT.md prose — what survived, what failed and why, recommended next step (paper-trade candidates; options overlay candidates), honest limitations.

## Self-review notes
- Spec coverage: engine semantics 1–9 → A4/A5 tests; gates → A5+C1/C2; all 12 strategies specified with exact rules; report → C3/D2. Rotation R-proxy decision documented in A5.
- Type consistency: `generate` returns entry_long/exit_long/stop_dist everywhere; Trade fields used by metrics match engine definition.
