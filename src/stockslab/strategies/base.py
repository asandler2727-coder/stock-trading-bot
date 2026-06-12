"""Strategy interfaces and registry for the stockslab backtest lab.

Frozen API contract — do not change signatures without updating all agents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import pandas as pd


@dataclass
class SignalStrategy:
    """Signal-based strategy. Engine semantics:
    - entry_long[t] True  -> enter at open[t+1] (unless entry_at_open, see gap_fade)
    - exit_long[t]  True  -> exit  at open[t+1]
    - stop_dist[t] ($ distance) defines initial stop at entry; R = pnl / stop_dist
    - target_r (R multiple) optional profit target; trail_atr_mult optional trailing stop
    - time_stop_bars optional max holding period
    - session_exit: intraday only — force exit at last bar of session close
    """

    name: str = "base"
    params: dict = field(default_factory=dict)
    timeframe: str = "1d"            # "1d" | "1h" | "5m"
    universe: str = "all"            # "all" | "stocks" | "etfs" | "levered"
    target_r: float | None = None
    trail_atr_mult: float | None = None
    time_stop_bars: int | None = None
    session_exit: bool = False
    entry_at_open: bool = False      # gap_fade only: entry signal uses bar t open, fills bar t open
    context: dict | None = None      # set by run_universe for cross-frame strategies

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return DataFrame indexed like df with columns:
        entry_long (bool), exit_long (bool), stop_dist (float, NaN when no entry).
        MUST be causal: row t uses data up to and including bar t close
        (or ONLY bar t open if entry_at_open).
        """
        raise NotImplementedError


@dataclass
class RotationStrategy:
    """Rebalance to equal-weight target list at each rebalance close; fills next open."""

    name: str = "base_rotation"
    params: dict = field(default_factory=dict)
    timeframe: str = "1d"
    universe: str = "all"

    def target_holdings(
        self,
        panel: dict[str, pd.DataFrame],
        dates: pd.DatetimeIndex,
    ) -> pd.DataFrame:
        """Return DataFrame index=rebalance dates (subset of dates), columns=symbols,
        values 0/1 membership. Row at date d may use data up to and including d close."""
        raise NotImplementedError


REGISTRY: dict[str, object] = {}


def register(cls):
    """Class decorator that instantiates the strategy and adds it to REGISTRY by name.

    Fails loud on two parallel-authoring footguns:
    - name still "base": the subclass forgot @dataclass (so the field default
      never took effect) or forgot to set a unique name. Either way it would
      silently clobber another entry.
    - duplicate name: two strategy modules chose the same name.
    """
    inst = cls()
    if inst.name == "base":
        raise ValueError(
            f"{cls.__name__} registered with name 'base' — set a unique `name` "
            "field and decorate the class with @dataclass so the default applies."
        )
    if inst.name in REGISTRY and type(REGISTRY[inst.name]) is not cls:
        raise ValueError(
            f"duplicate strategy name {inst.name!r}: already registered by "
            f"{type(REGISTRY[inst.name]).__name__}, now {cls.__name__}."
        )
    REGISTRY[inst.name] = inst
    return cls
