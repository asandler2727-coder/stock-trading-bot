from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from stockslab.strategies.base import RotationStrategy, register

_SECTOR_ETFS: tuple[str, ...] = (
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLU", "XLY", "XLB", "XLRE", "XLC",
)


@register
@dataclass
class SectorRotation(RotationStrategy):
    """Weekly rotation into the top-3 sector ETFs by average 1/3/6-month returns.

    Regime filter: only hold when SPY > SMA200; else all zeros.
    SPY must be present in the panel alongside the 11 sector ETFs.
    """

    name: str = "sector_rotation"
    timeframe: str = "1d"
    universe: str = "etfs"
    params: dict = field(default_factory=lambda: {
        "top_n": 3, "periods": [21, 63, 126], "trend_n": 200,
    })

    def target_holdings(
        self, panel: dict[str, pd.DataFrame], dates: pd.DatetimeIndex
    ) -> pd.DataFrame:
        p = self.params
        top_n = int(p.get("top_n", 3))
        periods = list(p.get("periods", [21, 63, 126]))
        trend_n = int(p.get("trend_n", 200))

        rebal_dates = [d for d in dates if d.weekday() == 0]
        sectors = [s for s in _SECTOR_ETFS if s in panel]
        if not rebal_dates or not sectors:
            return pd.DataFrame(
                index=pd.DatetimeIndex([], name="date"), columns=sectors
            )

        spy_df = panel.get("SPY")
        rows: dict[pd.Timestamp, dict[str, int]] = {}

        for d in rebal_dates:
            # Regime check
            if spy_df is not None:
                spy_hist = spy_df["close"].loc[:d]
                if len(spy_hist) >= trend_n:
                    spy_sma = spy_hist.rolling(trend_n, min_periods=trend_n).mean().iloc[-1]
                    regime_ok = spy_hist.iloc[-1] > spy_sma
                else:
                    regime_ok = False
            else:
                regime_ok = False

            if not regime_ok:
                rows[d] = {s: 0 for s in sectors}
                continue

            # Score each sector ETF by mean of 1/3/6-month returns
            scores: dict[str, float] = {}
            for sym in sectors:
                hist = panel[sym]["close"].loc[:d]
                period_returns: list[float] = []
                for lag in periods:
                    if len(hist) > lag and hist.iloc[-lag - 1] > 0:
                        ret = hist.iloc[-1] / hist.iloc[-lag - 1] - 1.0
                        if pd.notna(ret):
                            period_returns.append(ret)
                if period_returns:
                    scores[sym] = float(np.mean(period_returns))

            sorted_syms = sorted(scores, key=scores.__getitem__, reverse=True)
            top = set(sorted_syms[:top_n])
            rows[d] = {s: (1 if s in top else 0) for s in sectors}

        result = pd.DataFrame(rows).T
        result.index = pd.DatetimeIndex(result.index, name="date")
        return result.reindex(columns=sectors, fill_value=0)
