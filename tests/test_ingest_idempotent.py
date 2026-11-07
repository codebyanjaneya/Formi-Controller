"""Re-ingesting the same chunk (crash-replay) must not double-count anything."""
import json
import sys

sys.path.insert(0, ".")
from controller.store import Store
from controller.ingest import _ingest_one

EVENTS = [
    {"type": "lead", "event_id": 1, "ts": "2030-01-01T08:00:00+05:30", "workflow_id": "wf",
     "campaign_id": "wf:c1", "lead_id": "wf:l1", "person_id": "wf:p1",
     "features": {"lang": "hi", "city_tier": "1", "age_band": "31-45", "value_band": "mid"}},
    {"type": "call", "event_id": 2, "ts": "2030-01-01T09:00:00+05:30", "workflow_id": "wf",
     "campaign_id": "wf:c1", "lead_id": "wf:l1", "person_id": "wf:p1", "attempt_no": 1,
     "campaign_day_index": 0, "config_version": 1, "cohort_id": "default",
     "variant": {"welcome_message": "A", "voice": "B", "caller_id": "C", "prompt_version": "D"},
     "connected": True, "engaged": True, "disposition": "concluded_interested",
     "duration_s": 60, "turns": 9, "qa": {"hallucination_flag": False, "flow_adherence": 0.95}},
]
LINES = [json.dumps(e) for e in EVENTS]


def totals(store):
    agg = store.db.execute("SELECT COALESCE(SUM(dials),0), COALESCE(SUM(engaged),0)"
                           " FROM agg_calls").fetchone()
    nc = store.calls.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
    return agg + (nc,)


def test_reingest_same_chunk_is_noop(tmp_path):
    store = Store(str(tmp_path))
    _ingest_one(store, 5, LINES, last_event=-1)
    first = totals(store)
    assert first == (1, 1, 1)
    # crash-replay: same chunk again, cursor already moved
    last = int(store.get_meta("last_event_id"))
    _ingest_one(store, 5, LINES, last_event=last)
    assert totals(store) == first
    # replay with a stale in-memory cursor still cannot duplicate calls.db (PK event_id)
    _ingest_one(store, 5, LINES, last_event=-1)
    assert totals(store)[2] == 1
