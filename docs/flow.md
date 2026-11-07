# Flow map

Living map of the controller system. Everything below is **planned** — no controller code exists yet. Update this file in the same commit as every change.

## (a) Event flow diagram — planned

```mermaid
flowchart LR
    A[Events in via HTTP poll] --> B[State in SQLite]
    B --> C[Decisions / proposals]
    C --> D[Config changes out via HTTP]
```

## (b) Modules — planned

| Module/File | What it does | Imports / called by |
|---|---|---|
| _(planned)_ | | |

## (c) Simulator endpoints — observed via HTTP (step 3, public_01_dev)

Controller modules not built yet, so "Called by" is planned. Observed behaviour from live server + naive example run:

| Endpoint | Observed behaviour | Called by (planned) | Failure handling (planned) |
|---|---|---|---|
| `GET /health` | liveness check | startup wait loop | retry until up |
| `GET /sim/state` | `{scenario, sim_minute, ts, end_minute, finished, tick_minutes, credits_remaining, chunks, last_event_id}`. public_01_dev: tick=15min, end=11520min (8 sim days), 200 credits | main loop (stop when `finished`) | retry with backoff |
| `POST /sim/advance` `{minutes}` | advances sim time, returns state + `new_chunks` list; this is how time moves — sim is turn-based, not realtime | main loop | retry; advance is the clock, must not skip |
| `GET /events/chunks?kind=history` | pre-start history chunks (chunk 0 = events from 2026-12-21, before sim start 2027-01-04). Plain `GET /events/chunks` returned `[]` before advancing | startup (warm stats) | retry |
| `GET /events/chunks/{n}` | NDJSON, one event per line. Seen types: `campaign_created`, `lead` (features: lang, city_tier, age_band, value_band), `call` (has `connected`, `engaged`, `variant{voice,...}`) | event ingester | re-fetch chunk; chunks are immutable |
| `GET /workflows` | full policy per workflow: options per dim (welcome_message, voice, caller_id, prompt_version), objective + guardrail, governance (auto_apply dims/max_shift, approver_hours, proposal_ttl, apply_window, max_requests_per_24h, min_validation_pass_rate), mid_flight rule. 3 workflows in public_01_dev: nw_renewal, nw_kyc, ks_cancel | startup + periodic refresh (policy read at runtime, never hardcoded) | retry |
| `GET /workflows/{wid}/config` | `{workflow_id, version, actor, applied_at, config{cohorts, allocations{cohort→dim→{option: weight}}, prompt_version, schedule}}` | before proposing | retry |
| `PUT /workflows/{wid}/config` | auto-apply path (only governance-allowed dims, max_shift limit) | decision engine | handle 4xx = policy violation, don't retry blindly |
| `GET /workflows/{wid}/config/history` | past versions | not decided yet | — |
| `POST /approvals` | request human approval; 200 → `approval_id`; 422 `no_change` if proposed == current | decision engine | treat 422 as our bug |
| `GET /approvals` / `GET /approvals/{aid}` | status: pending → approved/rejected/expired/lapsed, with `reasons`. Observed: rejections ("approver declined (judgement call)") and expiries (ks_cancel approver window closed before TTL) | approval poller | retry |
| `POST /workflows/{wid}/apply` `{approval_id}` | applies an approved proposal → new version + `changed_dims`. Must happen within `apply_window_hours` | approval poller | handle lapsed window |
| `POST /llm/suggest-fixes` | observed: body `{workflow_id, problem}` (missing `problem` → `{"error":"missing_fields","detail":["problem"]}`). Returns `suggestions: [{prompt_version, summary}]` — just the prompt catalog reordered, no quality info. **Costs 3 credits** per call. Unknown workflow → `{"error":"unknown_workflow"}` | TBD | validate inputs before calling (credits are spent even if output is useless) |
| `POST /validation/runs` | observed: body `{workflow_id, prompt_version, n}` (bad prompt → `{"error":"bad_prompt_version"}`). Returns `{validation_run_id, failures, pass_rate, ts, credits_remaining}`. **Cost: 1 credit per 100 samples rounded up** (n=50→1, n=200→2). pass_rate is noisy: same prompt n=50 gave 0.98 then 1.00 — n=50 is too small to certify `min_validation_pass_rate: 0.97` | prompt-change gate | re-run / increase n before trusting a pass |

### Observed event types (beyond lead/call/campaign_created)

- `approval_decided` — `{approval_id, workflow_id, status: approved|rejected, reasons, ts}`; verified for BOTH approved and rejected cases (step 5); decision also visible by polling `GET /approvals/{aid}`.
- `config_changed` — `{workflow_id, version, actor, changed_dims, proposal_id, approval_id, ts}` emitted on apply. Also fires for EXTERNAL changes: `actor:"supervisor"` with null proposal/approval ids (step 6) — the controller's only reliable signal for supervisor edits.
- `call.qa` — `{hallucination_flag, flow_adherence}` on connected calls; baseline halluc rate ~1.3–1.7% (imperfect detector), flow_adherence mean ~0.93 (step 6).

### Error shapes observed

- 404 `{"error":"unknown_workflow","detail":"<wid>"}` (suggest-fixes, validation, approvals)
- 422 `{"error":"no_change"}` (proposal equal to current config)
- 422 `{"error":"missing_fields","detail":[...]}`, `{"error":"bad_prompt_version"}`
- 409 `{"error":"not_approved","detail":{"status":"applied"}}` (re-applying a used approval)

### Verified: why ks_cancel approvals always expired in the naive run

ks_cancel governance (from API): `proposal_ttl_hours: 12`, `approver_hours: [10,19]`. Naive submitted daily at 20:00 → proposal expires 08:00 next morning, but the approver only starts at 10:00. The approver never saw a single proposal. Fix is trivial: submit during (or shortly before) approver hours. Also: ks_cancel allows **auto-apply on voice/welcome_message/schedule/caller_id with max_shift 0.2** — most changes there don't need approval at all.

## (d) Proposal state machine — planned

_(planned)_

## (e) Storage & restart — planned

What is stored where in SQLite and what happens on restart: _(planned)_
