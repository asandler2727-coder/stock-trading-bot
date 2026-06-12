from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from stockslab.indicators import atr as calc_atr, ema, rsi
from stockslab.strategies.base import SignalStrategy, register


@register
@dataclass
class RsiDipUptrend(SignalStrategy):
    name: str = "rsi_dip_uptrend"
    timeframe: str = "1d"
    universe: str = "all"
    target_r: float | None = 2.0
    time_stop_bars: int | None = 15
    params: dict = field(default_factory=lambda: {
        "ema_slow": 200, "rsi_n": 14, "rsi_thresh": 40,
        "stop_mult": 1.5, "atr_n": 14,
    })

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.params
        ema200 = ema(df["close"], int(p.get("ema_slow", 200)))
        rsi_vals = rsi(df["close"], int(p.get("rsi_n", 14)))
        atr_vals = calc_atr(df, int(p.get("atr_n", 14)))
        rsi_thresh = float(p.get("rsi_thresh", 40))
        stop_mult = float(p.get("stop_mult", 1.5))

        uptrend = df["close"] > ema200
        oversold = rsi_vals < rsi_thresh

        entry = uptrend & oversold & atr_vals.notna()
        stop_dist = np.where(entry, stop_mult * atr_vals, np.nan)

        return pd.DataFrame(
            {
                "entry_long": entry,
                "exit_long": pd.Series(False, index=df.index),
                "stop_dist": stop_dist,
            },
            index=df.index,
        )
