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

### D005 — One process, one 15-min tick loop; SQLite WAL; Postgres as the written production path
- **Date**: 2026-11-07
- **Step**: 8 (design, see docs/design.md §1–3)
- **DECISION**: Single process, single loop (advance→ingest→detect→decide→act) on the sim's native 15-min tick; all state partitioned by workflow_id; SQLite in WAL mode as the store.
- **WHY**: The sim is turn-based — WE are the clock, so concurrency buys nothing; partition-by-workflow keeps the shard path open; SQLite = zero ops, one file, real transactions (crash safety needs those).
- **ALTERNATIVES**: async workers per workflow (rejected: complexity without wall-clock benefit in a turn-based world); Postgres now (rejected: an extra moving part for the grader's 4-vCPU box; kept as the written production path); in-memory + snapshot files (rejected: no atomic cursor+aggregate commit).
- **TRADE-OFF**: one slow workflow's decision work delays the tick for all; acceptable at ≤12 workflows, and the load test will measure it.
- **Would change our mind**: load-scenario ingest not keeping up single-threaded.
- **Files affected**: docs/design.md.

### D006 — Crash safety: deterministic proposal_id + intent log + cursor-with-data transaction
- **Date**: 2026-11-07
- **Step**: 8 (design §2–3)
- **DECISION**: (1) event cursor and aggregates commit in ONE SQLite transaction; (2) every outbound mutation writes an `intents` row BEFORE sending; (3) proposal_id = sha256(wid|base_version|diff|kind) so a resend after crash is the same id; (4) restart reconciles intents against GET /approvals + /config/history.
- **WHY**: README §5.8 (kill anywhere, resume, never double-apply). The sim's own idempotency (409 duplicate_proposal_id) only protects us if OUR id is stable across crashes — hence deterministic, not random.
- **ALTERNATIVES**: random UUID + "did I send it?" flag (rejected: flag write and send can't be atomic — the exact crash window we must survive); replaying the sim's events to rebuild intent state (rejected: events don't show proposals that were created but never decided... they do via GET /approvals, but intents also cover auto-apply PUTs and un-sent decisions).
- **TRADE-OFF**: every decision costs one extra DB write; negligible.
- **Files affected**: docs/design.md §2–4.

### D007 — Experiments: one dimension at a time, champion/challenger 70/30, Bonferroni winner test
- **Date**: 2026-11-07
- **Step**: 8 (design §Experiments)
- **DECISION**: Max one live experiment per workflow, one dimension at a time; challengers get 20–30% of traffic; judge only after step-5 min-n per arm; winner = two-proportion z-test, α=0.05 Bonferroni-corrected across challengers; guardrail checked before promotion; 24h decay watch after promotion with governance rollback.
- **WHY**: Step-5 power math (engagement tests only have power at workflow level; 2-D grids need ~4× samples); README §5.4 (deterministic winner, no LLM); naive run showed what 100% flips cost (one harmful change).
- **ALTERNATIVES**: multi-armed bandit (rejected: continuous reallocation fights mid_flight locks, auto-apply max_shift limits and approval latency — the environment is governance-gated, not a casino); full factorial welcome×voice (rejected: 4× samples, underpowered in short scenarios — interaction risk accepted and documented).
- **TRADE-OFF**: misses strong interactions; ~15–20% more samples for the correction (≈+1 day on a 5pp test) to keep false-winner rate ≤5%.
- **Would change our mind**: long scenarios with big volumes (then factorial on the biggest workflow becomes affordable).
- **Files affected**: docs/design.md §Experiments.

### D008 — Scope: build C1,C2,C5–C10(min),C12,C13,C14(min); cut C3-partial, C4, C11, C15
- **Date**: 2026-11-07
- **Step**: 8 (design §Scope)
- **DECISION**: As per docs/design.md §Scope, with reasons written per item.
- **WHY**: README §6 explicitly rewards choosing; the floor (public_01+02 end-to-end, audit, constraints) plus the evaluation table (outcomes, statistics, crash safety) points at exactly this set.
- **ALTERNATIVES**: building C4 call-time optimisation (real headroom, rejected to protect the experiment budget and scope); a UI for C11 (rejected: pure surface area).
- **TRADE-OFF**: leaves measurable schedule-headroom uncaptured on hidden scenarios.
- **Would change our mind**: finishing the build early (C4's hour_weights-only version is the first stretch goal).
- **Files affected**: docs/design.md §Scope.

### D009 — proposal_id gets an attempt number; customer-audible dims always via approval
- **Date**: 2026-11-07
- **Step**: 8b
- **DECISION**: (1) proposal_id = hash(wid|base_version|diff|kind|attempt); crash-retry keeps the attempt (same id, idempotent), deliberate re-proposal increments it (new id). (2) welcome_message/voice/prompt_version ALWAYS take the approval path; auto-apply only for caller_id/schedule where policy allows.
- **WHY**: (1) Without attempt, a legitimate re-proposal after expiry/reject is 409-duplicated forever. (2) Compliance wants named approval for anything a customer hears; supervisors want notice; and a 30% split is TV 0.3 > max_shift 0.2 anyway.
- **ALTERNATIVES**: random ids + sent-flag (rejected again: not crash-atomic); timestamp in the id (rejected: crash would mint a new id → double-send); using auto-apply for voice where policy allows with ≤max_shift splits (rejected: saves one approval but breaks the compliance/notice expectation — and small splits can't host a 30% challenger).
- **TRADE-OFF**: ~2 approvals per experiment → ≈2 experiments per workflow per 8–10 days. Accepted: governance hygiene scores; harmful-change count scores negatively.
- **Files affected**: docs/design.md §2, §5.

### D010 — Step-8b answers: 30% challenger, one retry, soft schedule, 20% credit reserve, Python+speed-gate
- **Date**: 2026-11-07
- **Step**: 8b
- **DECISION**: As per design.md "Decided questions" — challenger 30% (10pp in 1–2 days per workflow); one retry on judgement-call rejects with new attempt id, counted in max_requests_per_24h; schedule only as soft weights (no 0-weight hours in window) and only if time allows; credit reserve = 20% of starting credits from /sim/state; Python with an early ≥1400 events/sec ingest benchmark on public_03 (batch per chunk).
- **ALTERNATIVES**: 20% challenger (slower learning in short scenarios); unlimited retries (approver fatigue + request-cap burn); fixed 40-credit reserve (wrong on hidden budgets); zeroing bad hours in schedule (silently wastes capacity per SIMULATOR.md).
- **Files affected**: docs/design.md §Decided questions.
- **RESULT (Phase A)**: ingest benchmark on public_03 history (~5.5M events): **15,053 events/s** full path (fetch+parse+aggregate+calls.db+state txn) — 10× the 1400/s gate. Python confirmed.

### D011 — calls.db per-call record + `heard` CLI; client-preferences caution layer
- **Date**: 2026-11-07
- **Step**: 8b
- **DECISION**: Separate insert-only `calls.db` (one row per call: person, cohort_id, config_version, full variant, outcome) written in the same ingest batch, plus `python -m controller.why heard --person X --day Z` joining it to config_versions+audit. Client-stated preferences not in the API (Kestrel: ≤2 req/day, none before 11:00) become our own configurable caution settings, never looser than policy, logged as an assumption.
- **WHY**: Constraint §5.6: auditable from OUR store, sim logs don't count — aggregates alone cannot answer "why did person X hear variant Y on day Z". Separate file keeps the hot state DB small.
- **ALTERNATIVES**: gzip raw chunks + index (rejected: answering one person's question means scanning/decompressing days of NDJSON; also duplicates lead/campaign noise we don't need); per-call rows in the main DB (rejected: bloats the DB the tick loop fsyncs); storing only engaged/flagged calls (rejected: the compliance question is about ANY call).
- **TRADE-OFF**: ~60–80 MB/day on the load scenario + one more batched insert per chunk.
- **Files affected**: docs/design.md §2 (calls.db), §Client preferences layer.

### D012 — Pre-Phase-B checks: strict new-world detection; governance round-trip verified
- **Date**: 2026-11-07
- **Step**: Phase B prep
- **RESULTS**: (1) New-world detection = scenario name change OR sim_minute/last_event_id/chunk-count going backwards; tested both ways (same-world restart keeps state and resumes cursor 187400→191403; new world wipes + re-bootstraps). (2) Full governance round-trip verified with the controller's own modules: approval path (intent→sent→approved→applied) and auto-apply PUT (ack carries new version) — no bugs found. (3) Real `/config/history` shape confirmed: list of `{version, actor, changed_dims, applied_at, proposal_id, approval_id}` — reconcile's assumed shape was already correct. (4) Ingest bench with calls.db: **15,116 events/s**, controller-path memory ~250 MB steady / ~640 MB peak per 250k-line chunk (the 4.8 GB first reading was a bench-script artifact — it pre-fetched all 23 chunks; the controller never does).
- **Files affected**: controller/__main__.py (world_check, --max-ticks, credits in loop_health), scratch/governance_check.py, scratch/ingest_bench.py.

### D013 — Unit of analysis: calls, not persons (stated, not hidden)
- **Date**: 2026-11-07
- **Step**: Phase B
- **DECISION**: Experiments analyse dials (pickup KPI) / connected calls (engagement KPI) as the unit. The sim re-samples the variant on EVERY dial, so arm assignment is not clustered by person. Repeated attempts and returning persons correlate outcomes within arms, inflating variance somewhat; we do not model it, we buffer it (min-n floor 200, Bonferroni, 10pp-first judging) and state it.
- **ALTERNATIVES**: person-level analysis (first call per person only — throws away ~40% of data in short scenarios); mixed-effects models (defensible but unexplainable in a 60-min review and overkill at these n).
- **Would change our mind**: an A/A test showing false-winner rate above alpha (measured: 2.1–3.0% over 2000 random splits per workflow — under the 5% bound).
- **Files affected**: controller/experiments.py (docstring), scratch/aa_test.py.

### D014 — Phase B result and the price of governance hygiene
- **Date**: 2026-11-07
- **Step**: Phase B
- **RESULT**: public_01 with the experiment engine: **4 applied changes — 2 beneficial, 2 neutral, 0 harmful**; nw_kyc pickup +17.9% (caller_id experiment promoted D3 at 80/20); overall conclusion rate +6.2%. Voice experiments on nw_renewal/ks_cancel were still mid-flight at scenario end (min_n ≈460/arm at 15% traffic ≈ 3.3 days + approval latency both ways) — engagement headroom stays uncaptured on an 8-day scenario. That is the documented cost of D009 (audible dims via approval) + D007 (no judgement before min-n); on longer hidden scenarios the same machinery finishes.
- **Files affected**: reports/phaseB_public_01.md.

### D015 — One proposal starts the whole multi-arm test; two-look stopping rule
- **Date**: 2026-11-07
- **Step**: Phase C prep
- **DECISION**: (1) All untested options of a dimension enter ONE experiment as challengers (30% total traffic split evenly; one approval starts everything). (2) Winner judged at exactly two looks (min-n for 10pp, then min-n for 5pp), alpha split across looks and Bonferroni across challengers. (3) Clarified: "challenger share 30%" always meant 30% TOTAL.
- **WHY**: Sequential A/A replay with the naive every-tick rule showed 9.4–14% false winners (peeking inflates alpha); the two-look rule measured 1.0–4.0%, under the 5% bound. One proposal per test respects max_requests_per_24h and approver fatigue.
- **ALTERNATIVES**: test-every-tick (rejected: measured inflation); full sequential boundaries like O'Brien-Fleming (rejected: harder to defend, marginal gain over two looks at these n); one challenger at a time (rejected: burns one approval per option).
- **TRADE-OFF**: with k challengers each gets 30/k% traffic — more options = slower per arm; alpha/(k·looks) needs ~15–20% more n.
- **Files affected**: controller/experiments.py, scratch/aa_test_sequential.py, tests/test_decay.py.

### D016 — Remediation safety rails + daily baseline level recalibration
- **Date**: 2026-11-07
- **Step**: Phase C
- **DECISION**: (1) Daily recalibration of baseline LEVELS on live data (72h observed/expected, clamp [0.85, 1.15], skip series with open incidents) — history provides only the hourly SHAPE. (2) Caller-id rotation rails: target must be proven healthy (≥200 recent dials, pickup ≥ degraded+3pp); freed weight spread across all healthy options; no rotation of a slice carrying >85% of traffic; ≤8 auto-applies/wid/day; one open rotation per workflow.
- **WHY**: Measured failures in the first Phase-C run: a chronic ~2–3pp history-vs-live level offset caused daily false pickup alarms on every workflow; and a rotation onto a zero-data caller_id caused a 55-version auto-apply ping-pong storm (D1→D2→D1). Both are now impossible by construction.
- **ALTERNATIVES**: raising z/effect thresholds globally (rejected: also slows true-incident detection); baselines from live data only (rejected: hidden scenarios can open with an incident, poisoning the baseline).
- **TRADE-OFF**: a real slow drift smaller than the clamp (≤15% relative) is absorbed over days — accepted; the 24h backstop fires on anything bigger first.
- **Files affected**: controller/detect.py, controller/store.py (baseline_scale, detect_state tables).

### D017 — Phase C result (public_02)
- **Date**: 2026-11-07
- **RESULT**: **7 applied — 5 beneficial, 2 neutral, 0 harmful**; ALL conclusion +5.5%, ks_cancel +14.3%; engagement gap captured 16% overall (ks_cancel 31%); hallucinated calls 152 vs 416 baseline. Caller-ID incident: onset 10:00 → alarm + first auto-rotation 11:00 → rotation complete 11:30; flagged-DID share 0 from the next day. Bad-prompt incident: grader MTTR 315 min (edit 11:30 → halluc alarm + validated proposal 15:30 → applied 16:45; validation P1 pass_rate 0.985, n=200). Supervisor voice edit: detected via event, experiment invalidated, correctly NO counter-action (no KPI effect). Credits used 5/200.
- **Files affected**: reports/phaseC_public_02.md.

### D018 — All tuning constants in controller/tuning.py, each with its reason
- **Date**: 2026-11-07
- **Step**: Phase D prep (genericness audit)
- **DECISION**: Every threshold we own (z=3, 3pp floor, n≥300, ≥5 positives, 2-tick persistence, 24h cooldown, 4h/24h windows, 72h recalibration with [0.85,1.15] clamp, rotation rails 2pp/85%/200-dials/8-per-day, validation n=200, 20% credit reserve, 70/30 and 80/20 shares, alpha 0.05, 2 looks) lives in one file with a one-line reason each. Grep audit confirmed: no workflow ids, tenant names, option names or scenario dates anywhere in controller/ (exceptions: the `ks_`-prefix client-preference entry — a documented voluntary-caution assumption, D011 — and docstring examples in why.py).
- **WHY**: Hidden scenarios share only the schema; anything scenario-shaped in code is disqualifying. One file also makes the 60-min review's "change a constraint" question answerable by pointing at a line.
- **Files affected**: controller/tuning.py, controller/detect.py, controller/experiments.py.

### D019 — Guardrail test bounded by policy max_drop; no revert on guardrail block; retry actually retries
- **Date**: 2026-11-07
- **Step**: Phase D prep (public_01 regression)
- **PROBLEM FOUND**: rerunning public_01 produced 1 harmful change: the caller_id experiment found a true +13.2pp pickup winner (p=8e-9), but the guardrail check blocked promotion on ANY statistically significant engagement drop (a noise-level drop at n≈166), and `_revert` then threw away the measured-beneficial 70/15/15 split (didΔ −0.088 → harmful). Also found: D010's one-retry-after-reject never fired — a failed experiment permanently blocked its dimension (nw_kyc in public_02 sat idle after one random rejection).
- **FIX**: (1) guardrail blocks only on evidence the POLICY limit is breached: (drop > max_drop AND significant) OR drop > 2×max_drop. (2) On a guardrail block, keep the bounded split (no promotion, no revert) — its risk was accepted at start and the harm branch still protects it. (3) `dim_for` now returns (dim, attempt): failed/invalid experiments allow ONE fresh retry with a new attempt id.
- **RESULT**: public_01 rerun: 4 changes — 1 beneficial, 3 neutral, **0 harmful**; nw_kyc conclusion +19.0%.
- **ALTERNATIVES**: keeping strict any-significant-drop blocking (rejected: measured false block); promoting winners despite guardrail signal (rejected: policy limit is law).
- **Files affected**: controller/experiments.py, reports/phaseD_public_01.md.

### D020 — Phase D results: crash safety demonstrated, load target beaten 7×
- **Date**: 2026-11-07
- **RESULT**: (1) Crash test (scripts/crash_test.sh): one public_02 world, kill -9 at 5 distinct moments (intent written/unsent, proposal pending, approved-not-applied, mid auto-rotation, random) + restart each time → run completes, **11/11 invariants pass** (no double apply, no lost approval, cursor exact, state.db==calls.db, no unhandled duplicates). (2) Load test (reports/load_public_03.md): full controller in a 4-vCPU/8GB python:3.11 Linux container — **~1.3 min per simulated day** (target <10), ~11.3k events/s end-to-end, peak 801 MB, 32 governance actions across all 12 workflows. (3) 15 unit tests green (ids, winner stats, state machine, ingest idempotency, decay rollback). (4) `controller.health` + `controller.summary` CLIs are the C14/C11 minimal surfaces.
- **10× plan**: shard by workflow_id (every table already keyed by it); first bottleneck is the single-threaded tick loop, not memory or storage.
- **Files affected**: scripts/, tests/, controller/health.py, controller/summary.py, reports/crash_recovery.md, reports/load_public_03.md.

## Things we deliberately cut

_(none yet — planned)_
