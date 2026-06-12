from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from stockslab.indicators import atr as calc_atr
from stockslab.strategies.base import SignalStrategy, register


@register
@dataclass
class IntradayMomentum(SignalStrategy):
    """Intraday Momentum strategy. 1h bars."""
    name: str = "intraday_momentum"
    timeframe: str = "1h"
    universe: str = "etfs"
    session_exit: bool = True
    target_r: float | None = None
    params: dict = field(default_factory=lambda: {"threshold": 0.003, "atr_n": 14})

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        atr_n = int(self.params.get("atr_n", 14))
        threshold = float(self.params.get("threshold", 0.003))
        atr_vals = calc_atr(df, atr_n)

        dates = df.index.normalize()
        dates_s = pd.Series(dates.asi8, index=df.index)
        is_first_bar = (dates_s != dates_s.shift(1)).fillna(True)

        session_open = df["open"].where(is_first_bar).groupby(dates).transform("first")
        
        is_1230 = (df.index.hour == 12) & (df.index.minute == 30)

        ret_to_1230 = (df["close"] - session_open) / session_open
        entry = is_1230 & (ret_to_1230 > threshold)
        
        stop_dist = np.where(entry, atr_vals, np.nan)

        return pd.DataFrame(
            {
                "entry_long": entry,
                "exit_long": pd.Series(False, index=df.index),
                "stop_dist": stop_dist,
            },
            index=df.index,
        )
