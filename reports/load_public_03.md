# Load test — public_03 (12 workflows, ~650k dials/day, ~850k events/day)

**Environment (matches the grading box):** Docker container `python:3.11` on Linux,
`--cpus=4 --memory=8g`. Full controller (ingest + detection + experiments + governance),
not an ingest-only benchmark. Sim served from the host.

## Results

| Metric | Value | Target |
|---|---|---|
| wall-clock per simulated day | **72–81 s (~1.3 min)** | < 10 min ✓ (7× headroom) |
| total run (history bootstrap 5.5M events + 5 days / 4.2M live events) | 9 m 53 s | — |
| sustained end-to-end throughput | ~11,300 events/s (incl. detection + decisions each tick) | ≥ 1,400 ✓ |
| ingest-only benchmark (earlier, Windows) | 15,116 events/s | — |
| peak memory | **801 MB** | < 8 GB ✓ |
| decision lag | decisions are made in the same 15-min tick their events arrive; one full tick (ingest+detect+decide+act) averages ~0.75 s wall | — |
| governance activity during the run | 32 approval requests across all 12 workflows: 27 applied, 5 rejected, 0 expired/lapsed | — |
| credits | 400 → 400 (no incidents in public_03; experiments cost none) | no burn ✓ |
| CPU | user+sys ≈ 4.4 min over 9.9 min wall — single-threaded, ~45% of ONE core | — |

## What breaks first at 10×, and the shard plan

At 10× (8.5M events/day, ~120 workflows):

1. **First bottleneck: the single-threaded tick loop.** Ingest scales linearly (~12 min/day of
   pure processing at 10×, still under the target but with little slack), and the detect pass
   is per-workflow × per-series SQL over `agg_calls` — at 120 workflows it multiplies 10×.
   Still one process, so everything serializes.
2. **Second: SQLite write contention** between the per-chunk ingest transaction and the
   decision writes — WAL allows one writer at a time; at 10× the batches get big enough to
   make the loop bursty.
3. **Not a problem:** memory (flat aggregates, ~0.8 GB at 1×; calls.db is insert-only and
   disk-bound), credits, or the HTTP client.

**Sharding by workflow_id (already designed in, D005):** every table is keyed by
`workflow_id`; nothing joins across workflows. Split the workflow set over N processes, each
with its own SQLite file (or one Postgres with partitioned tables — the written production
path): a thin feeder fetches each chunk once and routes events to shards by `workflow_id`
(events carry it), or each shard filters the shared chunk stream. Governance and experiments
are already per-workflow, so they shard with zero logic changes. The only global state is
the credit budget — give the incident pipeline a per-shard allowance from the 20% reserve.

## Loop health

`python -m controller.health [--url SIM_URL]` prints ingest lag, decisions/day, credit burn,
open incidents and stuck proposals, and separates **page-on** conditions (ingest lag > 100k
events, credits below the 20% reserve, open hallucination incident, intents stuck in
pending_send) from **dashboard-only** noise (resolved incidents, normal rejections,
no-action incidents with a written reason).
