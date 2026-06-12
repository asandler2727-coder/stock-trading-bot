from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from stockslab.indicators import atr as calc_atr
from stockslab.strategies.base import SignalStrategy, register


@register
@dataclass
class Orb(SignalStrategy):
    """Opening Range Breakout — 1-hour bars.

    The opening range is defined by the first bar of each session.
    Entry when a later bar closes above the session's opening-range high.
    stop_dist = size of the opening range.
    session_exit forces exit at the last bar's close if still open.
    """

    name: str = "orb"
    timeframe: str = "1h"
    universe: str = "all"
    session_exit: bool = True
    target_r: float | None = 2.0
    params: dict = field(default_factory=lambda: {"atr_n": 14})

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        atr_n = int(self.params.get("atr_n", 14))
        atr_vals = calc_atr(df, atr_n)

        # Identify the first bar of each session (calendar day).
        # Use a pd.Series for shift — DatetimeIndex.shift requires a freq in pandas 3.
        dates = df.index.normalize()
        dates_s = pd.Series(dates.asi8, index=df.index)   # int64 is shift-safe
        is_first_bar = (dates_s != dates_s.shift(1)).fillna(True)

        # Build series of session open-range high and low (from the first bar)
        # Carry forward the first bar's high/low to all bars in the same session
        session_high = df["high"].where(is_first_bar).groupby(dates).transform("first")
        session_low = df["low"].where(is_first_bar).groupby(dates).transform("first")
        range_size = (session_high - session_low).clip(lower=1e-8)

        # Entry: not the first bar AND close exceeds session opening-range high
        entry = (~is_first_bar) & (df["close"] > session_high) & range_size.notna()
        # Use range_size as stop_dist (fall back to ATR if range is tiny / missing)
        stop = np.where(range_size.notna() & (range_size > 0), range_size, atr_vals)
        stop_dist = np.where(entry, stop, np.nan)

        return pd.DataFrame(
            {
                "entry_long": entry,
                "exit_long": pd.Series(False, index=df.index),
                "stop_dist": stop_dist,
            },
            index=df.index,
        )
