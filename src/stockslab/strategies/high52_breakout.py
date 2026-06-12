from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from stockslab.indicators import atr as calc_atr, sma
from stockslab.strategies.base import SignalStrategy, register


@register
@dataclass
class High52Breakout(SignalStrategy):
    name: str = "high52_breakout"
    timeframe: str = "1d"
    universe: str = "stocks"
    trail_atr_mult: float | None = 3.0
    params: dict = field(default_factory=lambda: {
        "breakout_n": 252, "vol_n": 50, "vol_mult": 1.5,
        "atr_n": 14, "stop_mult": 2.0,
    })

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.params
        bk_n = int(p.get("breakout_n", 252))
        vol_n = int(p.get("vol_n", 50))
        vol_mult = float(p.get("vol_mult", 1.5))
        atr_n = int(p.get("atr_n", 14))
        stop_mult = float(p.get("stop_mult", 2.0))

        # 52-week high of the HIGH column (shifted 1 so it excludes current bar)
        rolling_high = df["high"].rolling(window=bk_n, min_periods=bk_n).max().shift(1)
        avg_vol = sma(df["volume"], vol_n)
        atr_vals = calc_atr(df, atr_n)

        entry = (
            (df["high"] >= rolling_high)
            & rolling_high.notna()
            & (df["volume"] > vol_mult * avg_vol)
            & avg_vol.notna()
            & atr_vals.notna()
        )
        stop_dist = np.where(entry, stop_mult * atr_vals, np.nan)

        return pd.DataFrame(
            {
                "entry_long": entry,
                "exit_long": pd.Series(False, index=df.index),
                "stop_dist": stop_dist,
            },
            index=df.index,
        )
