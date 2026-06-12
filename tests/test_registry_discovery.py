"""Auto-discovery: importing stockslab.strategies must load every sibling
strategy module so their @register decorators populate REGISTRY, WITHOUT any
shared __init__.py edits (keeps strategy authoring parallel-safe). Also pins the
register() fail-loud guards that protect parallel authoring."""
from __future__ import annotations

import importlib
import textwrap

import pytest


def test_discovery_picks_up_a_correctly_written_strategy(tmp_path):
    import pathlib
    import stockslab.strategies as strat_pkg
    from stockslab.strategies.base import REGISTRY

    pkg_dir = pathlib.Path(strat_pkg.__file__).parent
    f = pkg_dir / "_tmp_probe_strategy.py"
    # Correct pattern: @register + @dataclass + unique name field default.
    f.write_text(textwrap.dedent('''
        from dataclasses import dataclass
        from stockslab.strategies.base import SignalStrategy, register
        @register
        @dataclass
        class _ProbeStrat(SignalStrategy):
            name: str = "_probe_strat"
    '''))
    try:
        importlib.reload(strat_pkg)
        strat_pkg.load_all()
        assert "_probe_strat" in REGISTRY
    finally:
        f.unlink()
        REGISTRY.pop("_probe_strat", None)


def test_register_rejects_missing_dataclass_or_name():
    # No @dataclass => inherited __init__ leaves name == "base" => must raise.
    from stockslab.strategies.base import SignalStrategy, register

    class _Broken(SignalStrategy):
        name: str = "should_not_apply_without_dataclass"

    with pytest.raises(ValueError):
        register(_Broken)


def test_load_all_is_idempotent():
    import stockslab.strategies as strat_pkg
    strat_pkg.load_all()
    strat_pkg.load_all()
    from stockslab.strategies.base import REGISTRY
    assert isinstance(REGISTRY, dict)
