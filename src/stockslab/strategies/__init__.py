"""Strategy package with filesystem auto-discovery.

Each strategy lives in its own module and decorates its class with @register
(from .base). Importing this package — or calling load_all() — imports every
sibling module so those decorators fire and populate REGISTRY. Strategy authors
therefore never edit a shared file, keeping parallel development conflict-free.
"""
from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

from stockslab.strategies.base import (  # re-export for convenience
    REGISTRY,
    RotationStrategy,
    SignalStrategy,
    register,
)

__all__ = ["REGISTRY", "SignalStrategy", "RotationStrategy", "register", "load_all"]

_SKIP = {"base", "__init__"}


def load_all() -> dict:
    """Import every sibling strategy module so @register decorators run.

    Idempotent: importlib caches modules, so repeated calls are cheap and do not
    re-register. Import errors propagate (fail loud) rather than hiding a broken
    strategy module.
    """
    pkg_path = Path(__file__).parent
    for mod in pkgutil.iter_modules([str(pkg_path)]):
        if mod.name in _SKIP:
            continue
        importlib.import_module(f"{__name__}.{mod.name}")
    return REGISTRY


# NOTE: discovery is NOT triggered at import time. Callers (the runner scripts)
# must call load_all() explicitly. This keeps `from stockslab.strategies.base
# import ...` cheap and — critically — avoids importing every sibling module
# while strategies are still being authored in parallel (a half-written sibling
# would otherwise break an unrelated module's import).
