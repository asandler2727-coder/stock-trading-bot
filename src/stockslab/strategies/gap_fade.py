from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from stockslab.indicators import sma
from stockslab.strategies.base import SignalStrategy, register


@register
@dataclass
class GapFade(SignalStrategy):
    """Fade an overnight gap-down on uptrending stocks.

    entry_at_open=True means the signal fires using bar-t's open; the engine
    fills at open[t]*(1+slip) on the same bar.  time_stop_bars=1 causes the
    engine to exit at bar-t's close (reason="time") since bars_held reaches 1
    within the same bar — this is the buy-open/sell-same-close round trip.
    """

    name: str = "gap_fade"
    timeframe: str = "1d"
    universe: str = "stocks"
    entry_at_open: bool = True
    time_stop_bars: int | None = 1
    params: dict = field(default_factory=lambda: {
        "gap_min": 0.02, "gap_max": 0.10, "sma_n": 50, "stop_pct": 0.05,
    })

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.params
        gap_min = float(p.get("gap_min", 0.02))
        gap_max = float(p.get("gap_max", 0.10))
        sma_n = int(p.get("sma_n", 50))
        stop_pct = float(p.get("stop_pct", 0.05))

        prev_close = df["close"].shift(1)
        sma50 = sma(df["close"], sma_n)

        # Uptrend: prior close > sma50 (causal: uses yesterday's close)
        uptrend = prev_close > sma50

        # Gap-down: today's open is 2–10% below yesterday's close
        gap_size = (prev_close - df["open"]) / prev_close
        gap_ok = (gap_size >= gap_min) & (gap_size <= gap_max)

        # With entry_at_open: row t's signal uses only bar t's open; all conditions
        # that reference prev_close or sma50 use data through bar t-1 close — causal.
        entry = uptrend & gap_ok & prev_close.notna() & sma50.notna()
        stop_dist = np.where(entry, stop_pct * prev_close, np.nan)

        # exit_long is unused (time_stop_bars=1 handles same-bar exit in engine)
        return pd.DataFrame(
            {
                "entry_long": entry,
                "exit_long": pd.Series(False, index=df.index),
                "stop_dist": stop_dist,
            },
            index=df.index,
        )
