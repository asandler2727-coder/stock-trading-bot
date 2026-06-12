from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from stockslab.indicators import atr as calc_atr, session_vwap
from stockslab.strategies.base import SignalStrategy, register


@register
@dataclass
class VwapReclaim(SignalStrategy):
    """VWAP Reclaim strategy. 1h bars."""
    name: str = "vwap_reclaim"
    timeframe: str = "1h"
    universe: str = "stocks"
    session_exit: bool = True
    target_r: float | None = 1.5
    params: dict = field(default_factory=lambda: {"atr_n": 14})

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        atr_n = int(self.params.get("atr_n", 14))
        atr_vals = calc_atr(df, atr_n)
        vwap = session_vwap(df)

        dates = df.index.normalize()
        dates_s = pd.Series(dates.asi8, index=df.index)
        is_first_bar = (dates_s != dates_s.shift(1)).fillna(True)

        first_bar_red = (df["open"] > df["close"]).where(is_first_bar).groupby(dates).transform("first")

        cross_above = (df["close"] > vwap) & (df["close"].shift(1) <= vwap.shift(1))
        prior_below = df["high"].shift(1) < vwap.shift(1)

        entry = cross_above & prior_below & first_bar_red & (~is_first_bar)
        
        stop_dist = np.where(entry, atr_vals, np.nan)

        return pd.DataFrame(
            {
                "entry_long": entry,
                "exit_long": pd.Series(False, index=df.index),
                "stop_dist": stop_dist,
            },
            index=df.index,
        )
