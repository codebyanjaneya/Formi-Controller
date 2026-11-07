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

### D002 — Probe credit-costing endpoints in a throwaway world before designing
- **Date**: 2026-11-06
- **Step**: 4 (grade + API probing)
- **DECISION**: Measure `/llm/suggest-fixes` (3 credits), `/validation/runs` (1 credit per 100 samples, rounded up) and the full approval→apply flow in a disposable serve run (`runs/probe01`) rather than guessing from docs.
- **WHY**: Credit budget (200) and approval timing directly shape controller strategy; measured facts beat assumptions in a defence review.
- **HOW**: Fresh server on :8700, deliberate bad requests for error shapes, duplicate validation runs for noise, one rejected and one approved→applied proposal observed end-to-end, then server killed.
- **ALTERNATIVES**: Reading sim source (forbidden); probing during the real graded run (rejected — wastes budget and pollutes results).
- **TRADE-OFF**: One extra throwaway run; 7 credits burnt in a world we discard.
- **Would change our mind**: n/a — probe is done.
- **Files affected**: `docs/flow.md`, `reports/naive_public_01.md`.
- **Key finding**: validation `pass_rate` at n=50 swung 0.98→1.00 for the same prompt; the 0.97 gate needs a larger n (≈1 failure in 50 = 0.98, so one unlucky sample flips the verdict). Budget for n≥200 when certifying a prompt change.
- **Key finding**: ks_cancel naive expiries were pure timing (TTL 12h vs submit at 20:00, approver starts 10:00) — proposal submission time is a first-class decision.
- **Note**: run `sim` CLI with `PYTHONUTF8=1` on Windows (grade report write crashes on cp1252 otherwise); sim/ untouched.

### D003 — Cohorts from history priors; live A/B only at coarse level
- **Date**: 2026-11-06
- **Step**: 5 (sizing analysis, see docs/analysis_step5.md)
- **DECISION**: Plan the controller around (a) cohort allocations seeded from 14-day history priors (age_band for engagement; city_tier + hour for pickup), and (b) live experiments only at whole-workflow level for engagement, at most single-feature level for pickup. Never test 2-feature cohorts live.
- **WHY**: Power math: engagement 5pp needs ~1550/arm; all 179 two-feature combos and all age_band values are TOO SMALL inside an 8-day scenario. History already establishes the feature splits at p<1e-17.
- **HOW**: Two-proportion sizing tables in docs/analysis_step5.md; analysis scripts in scratch/ (not controller/).
- **ALTERNATIVES**: Fine-grained live bandits per combo (rejected — noise-chasing, mathematically underpowered); no cohorts at all (rejected — age_band spread is 10–16pp, too big to ignore).
- **TRADE-OFF**: History priors ran under default config and may drift mid-run; we trust them for *who differs*, not for *which variant wins*.
- **Would change our mind**: live data contradicting a history prior at scale, or a scenario with much higher volumes.
- **Files affected**: docs/analysis_step5.md, scratch/fetch_history.py, scratch/analyze_history.py.

### D004 — Incident detection: event-driven first, sliced z-detector second
- **Date**: 2026-11-07
- **Step**: 6 (incident observation, see docs/analysis_step6.md)
- **DECISION**: Detect external/incident conditions with (1) `config_changed` actor≠controller as a hard signal with stat-reset, and (2) a rolling ~4h sliced z-detector (per workflow × dimension value) gated by hour-matched baselines, |z|≥3 AND effect ≥ max(3pp, 3×daily sd), n≥300 and ≥5 positives for rare metrics, plus a 24h slow-drift backstop.
- **WHY**: Measured on public_02: slice signal (−16.7pp) is 2× the aggregate; 4h window caught both measurable incidents in ≤2h; z-only detectors false-alarmed daily (afternoon pickup dip, 2pp baseline offsets, small-n halluc spikes). One supervisor edit had NO KPI signature — only the event reveals it.
- **HOW**: Rules written generically in analysis_step6.md §Generic detection rules; detector simulation code in scratch/analyze_probe03.py.
- **ALTERNATIVES**: 1h windows (too many false alarms); 24h-only (2–4h extra lag, flags trivial offsets); KPI-only detection without events (misses silent edits, cannot distinguish our changes from external ones).
- **TRADE-OFF**: 4h lag means ~a few hundred degraded calls before remediation; hour-matched baselines need history preprocessing.
- **Would change our mind**: a scenario whose history window is unrepresentative (then bootstrap baselines from the first live day(s)).
- **Files affected**: docs/analysis_step6.md, scratch/observe_run.py, scratch/analyze_probe03.py.

## Things we deliberately cut

_(none yet — planned)_
