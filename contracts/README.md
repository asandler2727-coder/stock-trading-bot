# contracts/

The **shared interface** between the research/backtest engine and the future trading copilot.

- The **engine lane** (`src/stockslab/`) *produces* results in this shape.
- The **trading-copilot lane** (future `trading-copilot/`) *consumes* them.

This boundary is a hard wall: the engine emits **descriptive** facts + point-in-time provenance and
**nothing prescriptive** — no risk limits, account/broker state, credentials, dollar sizing, or
execution instructions. Those live only in the copilot's rules layer.

**Current version: `0.2.0`** — reviewed by Codex; folds in signal identity, descriptive actionability
status, per-symbol stats, data-quality flags, and a reserved `live_signals` payload so the contract is
forward-ready for watchlist/scanner use without building a live generator yet.

## Files

| File | What it is |
|---|---|
| [`result_contract_v0.md`](result_contract_v0.md) | **Start here.** Normative spec: the boundary, point-in-time semantics + safety invariant, field→engine-source mapping, MUST-NOT-emit list, versioning, open questions for Codex, next steps for AGY. |
| [`result_contract.schema.json`](result_contract.schema.json) | Machine contract (JSON Schema, Draft 2020-12). Validate results against this. |
| [`examples/orb.result.example.json`](examples/orb.result.example.json) | Worked instance (orb, IS split). Conforms to the schema. |
| [`validate.py`](validate.py) | Reproducible checker for every example; also proves the safety guards reject violations. |

## Verify

```bash
.venv/bin/pip install jsonschema   # dev-only; not a runtime dep
.venv/bin/python contracts/validate.py
```

Expected:

```
schema OK: result_contract.schema.json (valid Draft 2020-12)
OK   orb.result.example.json: conforms

all examples valid; guards enforced
```

## The one invariant to remember

Every signal must satisfy:

```
data_available_at  <=  decision_valid_from
```

You may only act on a signal **after** the data that produced it was knowable. A copilot must reject
any signal that violates this. See §5 of the spec.

## Status

v0.2.0. Owned by the engine lane (Claude). Codex consumer-review complete (changes folded in).
Mechanical wiring + permanent tests come next, by AGY — see §14 of the spec.
