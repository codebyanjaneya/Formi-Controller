"""Synthetic decay test (no scenario names/dates in controller code — all data is fed here):

A promoted winner's true engagement fades after promotion. Assert the decay watch fires,
a rollback proposal goes through governance (intent row), and measure the delay in hours.

Run: python -m pytest tests/test_decay.py -s
"""
import json
import sys
from datetime import datetime, timedelta

sys.path.insert(0, ".")
from controller.store import Store
from controller import experiments


class FakeApi:
    """Only what _decay_watch -> current_alloc needs."""
    def __init__(self):
        self.version = 3

    def get_config(self, wid):
        return {"version": self.version,
                "config": {"allocations": {"default": {"voice": {"WIN": 0.8, "OLD": 0.2}}},
                           "prompt_version": "P1", "schedule": {}}}


POLICY = {"workflow_id": "wf_test",
          "options": {"voice": ["OLD", "WIN"]},
          "objective": {"primary": "engagement_rate", "guardrail": {"pickup_rate_max_drop": 0.02}},
          "governance": {"auto_apply": {"enabled": False, "allowed_dims": [], "max_shift": 0},
                         "approver_hours": [0, 24], "approver_latency_minutes": [0, 30],
                         "proposal_ttl_hours": 24, "apply_window_hours": 2,
                         "max_requests_per_24h": 10, "base_reject_rate": 0.0,
                         "min_validation_pass_rate": 0.97}}

T0 = datetime.fromisoformat("2030-06-01T00:00:00+05:30")
ONSET_H = 24  # true fade starts 24h after promotion


def hour_row(store, h, option, conn, eng):
    ts = (T0 + timedelta(hours=h)).isoformat()[:13]
    store.db.execute("INSERT INTO agg_calls VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     ("wf_test", ts, 3, "default", "W", option, "D", "P",
                      int(conn / 0.25), conn, eng, 0, 0, 0.9 * conn))


def test_decay_rollback(tmp_path):
    store = Store(str(tmp_path))
    store.db.execute("INSERT INTO workflows VALUES(?,?,?)",
                     ("wf_test", json.dumps(POLICY), T0.isoformat()))
    store.set_meta("end_minute", 10 * 1440)
    notes = {"promoted_winner": "WIN", "active_version": 3, "versions": [2, 3],
             "original_alloc": {"OLD": 1.0}, "split_alloc": {"OLD": 0.7, "WIN": 0.3},
             "min_n": 300}
    store.db.execute(
        "INSERT INTO experiments(exp_id,wid,dimension,cohort,arms,start_version,status,"
        "started_ts,winner,notes) VALUES(?,?,?,?,?,?,?,?,?,?)",
        ("exp_test", "wf_test", "voice", "default",
         json.dumps({"champion": "OLD", "challengers": ["WIN"]}), 2, "promoted",
         T0.isoformat(), "WIN", json.dumps(notes)))
    store.db.commit()

    api = FakeApi()
    fired_at = None
    for h in range(0, 96):
        # truth: winner engagement 0.60 before onset, 0.45 after; residual steady 0.55
        win_rate = 0.60 if h < ONSET_H else 0.45
        hour_row(store, h, "WIN", conn=160, eng=int(160 * win_rate))
        hour_row(store, h, "OLD", conn=40, eng=int(40 * 0.55))
        store.db.commit()
        now = (T0 + timedelta(hours=h + 1)).isoformat()
        experiments.step(api, store, now, {"sim_minute": (h + 1) * 60})
        row = store.db.execute("SELECT status FROM experiments WHERE exp_id='exp_test'").fetchone()
        if row[0] == "rollback_proposed":
            fired_at = h + 1
            break

    assert fired_at is not None, "decay watch never fired"
    intent = store.db.execute("SELECT kind, payload FROM intents").fetchone()
    assert intent is not None and intent[0] == "approval", "rollback must go through governance"
    payload = json.loads(intent[1])
    assert payload["proposed_config"]["allocations"]["default"]["voice"]["OLD"] == 0.8
    delay = fired_at - ONSET_H
    print(f"\ndecay onset at h{ONSET_H}, rollback proposed at h{fired_at} -> delay {delay}h")
    assert delay <= 36, f"detection too slow: {delay}h"
