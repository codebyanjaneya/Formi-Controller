# Crash-recovery evidence (public_02, one world, generated 2026-11-07T08:02:14Z)

Controller killed at five moments (os._exit(9) at the named hook = kill -9 semantics),
restarted each time with the same state dir, then run to completion.

## crash at: intent_written
- crashed as planned (exit 9), flag written; restarting
## crash at: proposal_pending
- crashed as planned (exit 9), flag written; restarting
## crash at: approved_before_apply
- crashed as planned (exit 9), flag written; restarting
## crash at: auto_pending
- crashed as planned (exit 9), flag written; restarting
## crash at: random (kill -9 after 15s)
- killed -9 mid-run; restarting
## final run to completion
- 2026-11-07 13:32:43,778 main INFO scenario finished at 2027-01-14T00:00:00+05:30 after 121 ticks, 16428 events
- 2026-11-07 13:32:43,778 main INFO peak memory: 56 MB

## invariants
```
PASS  scenario ran to completion
PASS  event cursor == sim last_event_id
PASS  no approved-but-never-applied proposal left  (0 stuck)
PASS  proposal state machine matches sim  ([])
PASS  no proposal applied twice  ([])
PASS  config versions complete for nw_renewal  (sim 4 vs ours 3; missing [])
PASS  config versions complete for nw_kyc  (sim 3 vs ours 2; missing [])
PASS  config versions complete for ks_cancel  (sim 8 vs ours 7; missing [])
PASS  no unsent intents left  (0)
PASS  no unhandled duplicate_proposal_id  (0)
PASS  agg_calls dials == calls.db rows  (245032 vs 245032)

info: approvals=9 lapsed=0 versions_total=12
```
invariants exit code: 0
