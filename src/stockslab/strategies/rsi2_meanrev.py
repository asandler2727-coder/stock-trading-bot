from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from stockslab.indicators import atr as calc_atr, rsi, sma
from stockslab.strategies.base import SignalStrategy, register


@register
@dataclass
class Rsi2Meanrev(SignalStrategy):
    name: str = "rsi2_meanrev"
    timeframe: str = "1d"
    universe: str = "stocks"
    time_stop_bars: int | None = 10
    params: dict = field(default_factory=lambda: {
        "sma_n": 200, "sma_fast": 5, "rsi_n": 2,
        "rsi_entry": 10, "rsi_exit": 70, "stop_mult": 2.5, "atr_n": 14,
    })

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.params
        sma200 = sma(df["close"], int(p.get("sma_n", 200)))
        sma5 = sma(df["close"], int(p.get("sma_fast", 5)))
        rsi2 = rsi(df["close"], int(p.get("rsi_n", 2)))
        atr_vals = calc_atr(df, int(p.get("atr_n", 14)))
        rsi_entry = float(p.get("rsi_entry", 10))
        rsi_exit = float(p.get("rsi_exit", 70))
        stop_mult = float(p.get("stop_mult", 2.5))

        entry = (df["close"] > sma200) & (rsi2 < rsi_entry) & atr_vals.notna()
        exit_ = (rsi2 > rsi_exit) | (df["close"] > sma5)
        stop_dist = np.where(entry, stop_mult * atr_vals, np.nan)

        return pd.DataFrame(
            {"entry_long": entry, "exit_long": exit_, "stop_dist": stop_dist},
            index=df.index,
        )
