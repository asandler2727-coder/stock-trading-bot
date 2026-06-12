# StocksLab Backtest Audit Synthesis Report (Phase D2)

## 1. Executive Summary

This report synthesizes the adversarial audit findings from Phase D1 of the StocksLab project. Out of an initial universe of 12 strategies that passed the preliminary Profit Factor (PF) > 1.3 gate, four representative strategies underwent deep-dive auditing to verify logic integrity, data quality, and performance distribution.

*   **2 CONFIRMED:** `donchian_breakout` and `high52_breakout` passed with clean audits. They showed no logic deviations, healthy trade distributions, and no significant data artifacts.
*   **2 REVIEW:** `xsec_momentum` and `bb_squeeze_breakout` had their Profit Factors verified but remain under "Review" status due to specific caveats—extreme regime dependency for momentum and marginal edge for the squeeze breakout.
*   **Audit Scope Note:** Only 4 of the 12 "gate-passing" strategies were audited. The high failure rate at the gate (8 out of 12) suggests significant survivorship and reporting bias in the initial candidate pool.

---

## 2. Per-Strategy Audit Results

### xsec_momentum
| Metric | Value |
| :--- | :--- |
| **IS PF** | 3.326 |
| **IS N** | 651 |
| **OOS PF** | 2.212 |
| **Verdict** | **REVIEW** |

**Key Findings:**
*   **Regime Dependency:** Performance is heavily skewed by the 2020-2021 bull run. The PF for this period was 8.129, compared to a more representative pre-2020 PF of 2.591.
*   **Concentration Risk:** The top 3 trades (TSLA and NVDA) contribute 30.5% of total gains. TSLA alone accounts for 13% of all gains.
*   **Logic Fragility:** 
    1.  An off-by-one error in momentum calculation (~2% impact).
    2.  Holiday fragility: The rebalance logic skips weeks where Monday is a market holiday without a fallback mechanism.
*   **Qualification:** While a genuine momentum factor exists, the gate metrics are overstated by the extreme 2021 market.

### donchian_breakout
| Metric | Value |
| :--- | :--- |
| **IS PF** | 1.624 |
| **IS N** | 2,698 |
| **OOS PF** | 1.361 |
| **Verdict** | **CONFIRM** |

**Key Findings:**
*   **Integrity:** Logic matches the specification exactly across all parameters. PF verified with negligible delta (0.0003).
*   **Distribution:** This strategy produced the most trades and the healthiest distribution of the set. Top-3 symbols contribute only 5.82% of gains.
*   **Qualification:** Highest confidence candidate. Solid, simple trend-following logic that scales well across symbols.

### high52_breakout
| Metric | Value |
| :--- | :--- |
| **IS PF** | 1.515 |
| **IS N** | 812 |
| **OOS PF** | 1.322 |
| **Verdict** | **CONFIRM** |

**Key Findings:**
*   **Verification:** All 5 logic items match implementation perfectly. Distribution is well-diversified (top-3 symbols = 11%).
*   **Artifacts:** Identified 25 split-adjusted trades with entry prices < $5.0 (2011-2017). While common in backtesting, it does not invalidate the overall positive expectancy.
*   **Qualification:** A clean, reliable breakout strategy with solid diversification.

### bb_squeeze_breakout
| Metric | Value |
| :--- | :--- |
| **IS PF** | 1.313 |
| **IS N** | 1,471 |
| **OOS PF** | 1.171 |
| **Verdict** | **REVIEW** |

**Key Findings:**
*   **Edge:** Narrowest profit factor of the audited set, barely clearing the 1.3 gate.
*   **Verification:** Logic matches spec. Distribution is healthy (top-3 symbols 6.39%).
*   **Qualification:** The strategy is technically sound but marginal. It possesses the smallest edge of the confirmed/reviewed set.

---

## 3. Notable Failures

The following strategies failed to advance to the D1 audit or exhibited highly suspicious behavior:

*   **levered_etf_meanrev (OOS PF 1.556 > IS PF 1.116):** This anomalous reversal (OOS outperforming IS) is a hallmark of data mining. The strategy likely "accidentally" fit the OOS regime. It should be treated as high-risk/overfit.
*   **rsi2_meanrev (IS PF 1.287):** A narrow miss of the 1.3 gate despite a high trade count (4,130). This provides high statistical confidence that the edge is insufficient for the current parameters.
*   **ema_pullback (15 IS trades):** Not a viable strategy. This result indicates a signal filtering bug where conditions are too restrictive for any meaningful execution.

---

## 4. Paper-Trade Recommendations

Ranked by confidence for immediate paper-trading:

1.  **donchian_breakout:** Highest confidence. Simplest logic, highest trade count, and most robust distribution.
2.  **high52_breakout:** Solid second candidate. Clean audit and reliable diversification.
3.  **xsec_momentum:** High performance but needs caution. Requires position sizing controls and regime detection to mitigate its extreme dependency on high-momentum bull runs.
4.  **bb_squeeze_breakout:** Lowest priority due to its marginal edge.

---

## 5. Honest Limitations

*   **Survivorship Bias:** The 4 audited strategies are the "winners" of an unknown universe. Their performance may not be representative of future results.
*   **Regime Inflation:** The 2020-2021 bull market significantly inflates the metrics for all strategies, particularly momentum. Pre-2020 performance should be the baseline for expectations.
*   **Intraday Approximations:** Strategies referencing 1h data rely on approximations from daily fills, introducing potential execution slippage not captured in the backtest.
*   **Fragile Logic Patterns:** Patterns like the `shift()`-based momentum calculation in `xsec_momentum` are fragile and carry a risk of unintended lookahead if not strictly maintained.
