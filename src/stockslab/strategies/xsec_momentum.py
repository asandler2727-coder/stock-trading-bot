from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from stockslab.indicators import sma
from stockslab.strategies.base import RotationStrategy, register


@register
@dataclass
class XsecMomentum(RotationStrategy):
    """Cross-sectional momentum rotation — weekly, top-10 by 12-1 momentum.

    Rebalances every Monday. Regime filter: only hold when SPY > SMA200; emit
    empty (all zeros) when SPY is below. SPY must be present in the panel
    (runner should include it alongside the stock universe).
    """

    name: str = "xsec_momentum"
    timeframe: str = "1d"
    universe: str = "stocks"
    params: dict = field(default_factory=lambda: {
        "top_n": 10, "mom_long": 252, "mom_short": 21, "trend_n": 200,
    })

    def target_holdings(
        self, panel: dict[str, pd.DataFrame], dates: pd.DatetimeIndex
    ) -> pd.DataFrame:
        p = self.params
        top_n = int(p.get("top_n", 10))
        mom_long = int(p.get("mom_long", 252))
        mom_short = int(p.get("mom_short", 21))
        trend_n = int(p.get("trend_n", 200))

        # Rebalance on every Monday present in dates
        rebal_dates = [d for d in dates if d.weekday() == 0]
        if not rebal_dates:
            return pd.DataFrame(
                index=pd.DatetimeIndex([], name="date"), columns=list(panel.keys())
            )

        spy_df = panel.get("SPY")
        tradeable = [s for s in panel if s != "SPY"]

        rows: dict[pd.Timestamp, dict[str, int]] = {}
        for d in rebal_dates:
            # Regime: SPY close > SPY SMA200 at date d
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
                rows[d] = {s: 0 for s in tradeable}
                continue

            # 12-1 momentum: return from mom_long bars ago to mom_short bars ago
            scores: dict[str, float] = {}
            for sym in tradeable:
                hist = panel[sym]["close"].loc[:d]
                if len(hist) < mom_long + 1:
                    continue
                price_long = hist.iloc[-mom_long]
                price_short = hist.iloc[-mom_short]
                if price_long > 0 and pd.notna(price_long) and pd.notna(price_short):
                    scores[sym] = price_short / price_long - 1.0

            sorted_syms = sorted(scores, key=scores.__getitem__, reverse=True)
            top = set(sorted_syms[:top_n])
            rows[d] = {s: (1 if s in top else 0) for s in tradeable}

        result = pd.DataFrame(rows).T
        result.index = pd.DatetimeIndex(result.index, name="date")
        return result.reindex(columns=tradeable, fill_value=0)
