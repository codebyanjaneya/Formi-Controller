# CLAUDE.md — standing rules (read every session)

PROJECT: Round 2 take-home "Outcome-First Agent Loop" (see README.md). Anjaneya must defend every line in a 60-minute review, so he must understand everything.

## HARD RULES
- Controller code lives in `controller/` and talks to the simulator ONLY over HTTP. Never import `sim`, never read `runs/`, never read or parse `scenarios/*.yaml` from controller code. Never modify `sim/`. Never use hidden-truth fields.
- `./run.sh <SIM_URL>` must run the controller with no manual steps until the scenario ends.
- Never hardcode workflow policy; read it at runtime from the API.
- Follow README section 5 constraints always.

## WORKING STYLE
- Work in small steps. Before each step: explain in simple Hinglish what you will do and why, then WAIT for Anjaneya's "go".
- After each step: explain what was done, why, and how, in simple Hinglish. Then print a section "NOTEBOOK POINTS" listing only the important things to note down. Then WAIT for confirmation before the next step.
- Ask before any big design choice; offer 2-3 options with trade-offs and a recommendation.
- Small honest commits, one per logical change, clear messages.
- After EVERY change, update `docs/decisions.md` and `docs/flow.md` in the same commit.
