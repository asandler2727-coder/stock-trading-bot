from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from stockslab.indicators import atr as calc_atr, donchian_high, donchian_low
from stockslab.strategies.base import SignalStrategy, register


@register
@dataclass
class DonchianBreakout(SignalStrategy):
    name: str = "donchian_breakout"
    timeframe: str = "1d"
    universe: str = "all"
    trail_atr_mult: float | None = 3.0
    params: dict = field(default_factory=lambda: {"breakout_n": 55, "exit_n": 20, "atr_n": 14})

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.params
        bk_n = int(p.get("breakout_n", 55))
        exit_n = int(p.get("exit_n", 20))
        atr_n = int(p.get("atr_n", 14))

        dh = donchian_high(df, bk_n).shift(1)   # prior-bar high — causal
        dl = donchian_low(df, exit_n).shift(1)   # prior-bar low  — causal
        atr_vals = calc_atr(df, atr_n)

        entry = (df["close"] > dh) & dh.notna() & atr_vals.notna()
        exit_ = (df["close"] < dl) & dl.notna()
        stop_dist = np.where(entry, 2.0 * atr_vals, np.nan)

        return pd.DataFrame(
            {"entry_long": entry, "exit_long": exit_, "stop_dist": stop_dist},
            index=df.index,
        )
