#!/usr/bin/env python3
"""Reproducible validator for the strategy-result contract.

Validates every example under contracts/examples/ against the JSON Schema, and
asserts the two safety guards actually bite (forbidden engine/copilot-boundary
fields are rejected; timezone-naive timestamps are rejected).

Usage:
    .venv/bin/python contracts/validate.py

Dependency: jsonschema (dev-only; not a runtime dependency of the engine).
AGY follow-up: promote these checks into tests/ (see result_contract_v0.md).
"""
from __future__ import annotations

import copy
import json
import pathlib
import sys

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - dev tooling hint
    print("jsonschema not installed. Run: .venv/bin/pip install jsonschema", file=sys.stderr)
    sys.exit(2)

HERE = pathlib.Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "result_contract.schema.json"
EXAMPLES_DIR = HERE / "examples"


def _load(path: pathlib.Path) -> dict:
    with path.open() as fh:
        return json.load(fh)


def main() -> int:
    schema = _load(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    print(f"schema OK: {SCHEMA_PATH.name} (valid Draft 2020-12)")

    examples = sorted(EXAMPLES_DIR.glob("*.json"))
    if not examples:
        print("no examples found", file=sys.stderr)
        return 1

    failures = 0
    for path in examples:
        instance = _load(path)
        errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
        if errors:
            failures += 1
            print(f"FAIL {path.name}: {len(errors)} error(s)")
            for err in errors:
                loc = "/".join(map(str, err.path)) or "<root>"
                print(f"  - at {loc}: {err.message}")
            continue
        print(f"OK   {path.name}: conforms")

        # Each guard mutates a copy and asserts the schema REJECTS it. A guard
        # that fails (mutation accepted) means the contract boundary has a hole.
        def _boundary(inst):
            m = dict(inst)
            m["max_daily_loss"] = 500  # smuggle prescriptive risk policy
            return m

        def _naive_ts(inst):
            m = copy.deepcopy(inst)
            m["signals"][0]["data_available_at"] = "2024-03-05T11:30:00"  # no tz offset
            return m

        def _live_needs_inputs(inst):
            m = copy.deepcopy(inst)
            m["strategy"]["live_capable"] = True
            m["signals"][0]["required_inputs"] = None  # live + missing inputs
            return m

        def _backtest_needs_stats(inst):
            m = copy.deepcopy(inst)
            m["payload_type"] = "backtest_result"
            m.pop("empirical_risk_stats", None)
            return m

        def _live_needs_refs(inst):
            m = copy.deepcopy(inst)
            m["payload_type"] = "live_signals"
            m.pop("validation_refs", None)  # live payload must reference a validation run
            return m

        guards = [
            ("forbidden boundary field rejected", _boundary, True),
            ("timezone-naive timestamp rejected", _naive_ts, bool(instance.get("signals"))),
            ("live_capable requires required_inputs", _live_needs_inputs, bool(instance.get("signals"))),
            ("backtest_result requires empirical_risk_stats", _backtest_needs_stats, True),
            ("live_signals requires validation_refs", _live_needs_refs, True),
        ]
        for label, mutate, applicable in guards:
            if not applicable:
                continue
            if not list(validator.iter_errors(mutate(instance))):
                failures += 1
                print(f"  GUARD FAIL ({path.name}): {label} — mutation was ACCEPTED")

    if failures:
        print(f"\n{failures} failure(s)")
        return 1
    print("\nall examples valid; guards enforced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
