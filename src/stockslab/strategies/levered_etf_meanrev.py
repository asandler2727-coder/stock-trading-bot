from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from stockslab.indicators import atr as calc_atr, rsi, sma
from stockslab.strategies.base import SignalStrategy, register


@register
@dataclass
class LeveredEtfMeanrev(SignalStrategy):
    """Mean-reversion on leveraged ETFs, gated by QQQ>SMA200 regime.

    Regime data comes from self.context (set by run_universe) or, if context
    is absent / missing QQQ, from stockslab.data.load_panel — cache-only,
    no network call.
    """

    name: str = "levered_etf_meanrev"
    timeframe: str = "1d"
    universe: str = "levered"
    time_stop_bars: int | None = 10
    params: dict = field(default_factory=lambda: {
        "rsi_n": 2, "rsi_entry": 10, "rsi_exit": 65,
        "regime_n": 200, "stop_mult": 3.0, "atr_n": 14,
    })

    def _qqq_close(self, df: pd.DataFrame) -> pd.Series:
        """Return QQQ close series aligned to df.index, sourced from context or cache."""
        ctx = getattr(self, "context", None) or {}
        qqq_df = ctx.get("QQQ") if isinstance(ctx, dict) else None
        if qqq_df is None:
            from stockslab.data import load_panel
            panel = load_panel(["QQQ"], "1d")
            qqq_df = panel.get("QQQ")
        if qqq_df is None:
            return pd.Series(np.nan, index=df.index)
        return qqq_df["close"].reindex(df.index, method="ffill")

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.params
        rsi_n = int(p.get("rsi_n", 2))
        rsi_entry = float(p.get("rsi_entry", 10))
        rsi_exit = float(p.get("rsi_exit", 65))
        regime_n = int(p.get("regime_n", 200))
        stop_mult = float(p.get("stop_mult", 3.0))
        atr_n = int(p.get("atr_n", 14))

        rsi_vals = rsi(df["close"], rsi_n)
        atr_vals = calc_atr(df, atr_n)

        qqq_close = self._qqq_close(df)
        qqq_sma = sma(qqq_close, regime_n)
        regime_ok = (qqq_close > qqq_sma) & qqq_sma.notna()

        entry = regime_ok & (rsi_vals < rsi_entry) & atr_vals.notna()
        exit_ = rsi_vals > rsi_exit
        stop_dist = np.where(entry, stop_mult * atr_vals, np.nan)

        return pd.DataFrame(
            {"entry_long": entry, "exit_long": exit_, "stop_dist": stop_dist},
            index=df.index,
        )
