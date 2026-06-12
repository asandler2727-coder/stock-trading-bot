# Stockslab Phase C Report

## Strategy Rankings

| Strategy | IS PF | IS WR | IS N | OOS PF | OOS WR | OOS N | IS MaxDD(1%) | Min Rob PF | 2x Slip PF | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| xsec_momentum | 3.33 | 56.22% | 651 | 2.21 | 53.70% | 216 | 11.50% | 2.98 | 3.61 | Pass OOS |
| sector_rotation | 2.03 | 53.64% | 330 | 2.05 | 50.51% | 99 | 4.10% | 2.03 | 0.00 | Fail |
| donchian_breakout | 1.62 | 41.77% | 2698 | 1.36 | 37.03% | 948 | 71.56% | 1.51 | 1.49 | Pass OOS |
| high52_breakout | 1.52 | 41.01% | 812 | 1.32 | 36.60% | 194 | 27.72% | 1.39 | 1.42 | Pass OOS |
| rsi_dip_uptrend | 1.39 | 47.04% | 5423 | 1.29 | 45.72% | 1649 | 77.14% | 1.28 | 1.33 | Pass OOS |
| bb_squeeze_breakout | 1.31 | 36.37% | 1471 | 1.17 | 34.70% | 562 | 42.09% | 1.26 | 1.26 | Pass OOS |
| rsi2_meanrev | 1.29 | 66.17% | 4130 | 1.10 | 63.10% | 1252 | 41.60% | 1.29 | 0.00 | Fail |
| levered_etf_meanrev | 1.12 | 63.15% | 1042 | 1.56 | 65.38% | 338 | 20.67% | 1.12 | 0.00 | Fail |
| gap_fade | 1.10 | 51.10% | 1141 | 0.79 | 47.65% | 533 | 11.73% | 1.10 | 0.00 | Fail |
| intraday_momentum | 0.96 | 49.83% | 2619 | 0.88 | 47.63% | 1310 | 65.80% | 0.96 | 0.00 | Fail |
| vwap_reclaim | 0.96 | 48.04% | 1020 | 0.68 | 41.87% | 578 | 42.03% | 0.96 | 0.00 | Fail |
| orb | 0.91 | 46.54% | 13841 | 0.95 | 46.69% | 6569 | 99.75% | 0.91 | 0.00 | Fail |

## Caveats

- **Survivorship Bias**: Daily historical data does not include delisted symbols.

- **Thin Intraday Data**: The intraday data window is short and recent.

- **Regime Dependence**: The out-of-sample window may just be a different regime.
