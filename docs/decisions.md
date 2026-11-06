# Decisions log

Running log of every design decision. One entry per decision, newest at the bottom.

Entry format:
- **ID**: D001, D002, ...
- **Date**
- **Step**
- **DECISION**
- **WHY** we chose it
- **HOW** it works (short)
- **ALTERNATIVES** rejected and why not
- **TRADE-OFF** / what it costs
- **What would change our mind**
- **Files affected**

## Decisions

### D001 — Local venv + observe API over HTTP only
- **Date**: 2026-11-06
- **Step**: 3 (environment setup)
- **DECISION**: Use a project-local `.venv` (Python 3.14), install from `requirements.txt`, and learn the simulator's behaviour only by calling its HTTP API (`/openapi.json`, `/workflows`, `/sim/state`, event chunks) plus running `examples/naive_controller.py` — never by reading `sim/*.py` or `scenarios/*.yaml`.
- **WHY**: The take-home forbids the controller from using anything but the HTTP API; learning the API the same way keeps our mental model honest and defensible.
- **HOW**: `python -m venv .venv`; baseline run saved to `runs/base01`; served `public_01_dev` on :8700 with `--run-dir runs/naive01`; naive controller driven to scenario end; server killed afterwards (its world is consumed).
- **ALTERNATIVES**: Reading sim source (rejected — against the spirit/rules); Docker (rejected — unnecessary for a single-process Python sim).
- **TRADE-OFF**: Some endpoint semantics (`/llm/suggest-fixes`, `/validation/runs`, credit costs) remain unknown until we probe them deliberately.
- **Would change our mind**: README explicitly permitting source reading for API docs.
- **Files affected**: `.venv/` (untracked), `runs/` (untracked), `docs/flow.md`.

## Things we deliberately cut

_(none yet — planned)_
