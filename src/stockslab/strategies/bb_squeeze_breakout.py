from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from stockslab.indicators import atr as calc_atr, bb
from stockslab.strategies.base import SignalStrategy, register


@register
@dataclass
class BbSqueezeBreakout(SignalStrategy):
    name: str = "bb_squeeze_breakout"
    timeframe: str = "1d"
    universe: str = "all"
    trail_atr_mult: float | None = 2.5
    params: dict = field(default_factory=lambda: {
        "bb_n": 20, "bb_k": 2.0, "squeeze_pctile": 15,
        "lookback": 252, "atr_n": 14, "stop_mult": 2.0,
    })

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.params
        bb_n = int(p.get("bb_n", 20))
        bb_k = float(p.get("bb_k", 2.0))
        pctile = float(p.get("squeeze_pctile", 15))
        lookback = int(p.get("lookback", 252))
        atr_n = int(p.get("atr_n", 14))
        stop_mult = float(p.get("stop_mult", 2.0))

        _, bb_upper, _, bb_width = bb(df["close"], bb_n, bb_k)
        atr_vals = calc_atr(df, atr_n)

        # squeeze: current width <= pctile-th percentile of trailing lookback window
        width_thresh = bb_width.rolling(window=lookback, min_periods=lookback).quantile(pctile / 100.0)
        in_squeeze = (bb_width <= width_thresh) & width_thresh.notna()

        # entry: squeeze on prior bar AND close breaks above upper band today
        entry = in_squeeze.shift(1).fillna(False).astype(bool) \
            & (df["close"] > bb_upper) & bb_upper.notna() \
            & atr_vals.notna()
        stop_dist = np.where(entry, stop_mult * atr_vals, np.nan)

        return pd.DataFrame(
            {
                "entry_long": entry,
                "exit_long": pd.Series(False, index=df.index),
                "stop_dist": stop_dist,
            },
            index=df.index,
        )
