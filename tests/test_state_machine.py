"""Proposal state machine against a scripted fake sim: applied / double-apply / lapse / stale."""
import json
import sys

sys.path.insert(0, ".")
from controller.api import ApiError
from controller.store import Store
from controller import govern


class FakeApi:
    def __init__(self, approval_status, apply_error=None, apply_detail=None):
        self.approval_status = approval_status
        self.apply_error = apply_error
        self.apply_detail = apply_detail
        self.applies = 0

    def get_approval(self, aid):
        return {"approval_id": aid, "status": self.approval_status, "reasons": []}

    def apply(self, wid, aid):
        self.applies += 1
        if self.apply_error:
            raise ApiError(409 if self.apply_error != "lapsed" else 410,
                           "not_approved" if self.apply_error == "not_approved" else
                           ("stale_base_version" if self.apply_error == "stale" else "lapsed"),
                           self.apply_detail)
        return {"workflow_id": wid, "version": 2, "changed_dims": ["voice"]}


def seed(store, status="pending"):
    store.db.execute("INSERT INTO proposals(proposal_id,approval_id,wid,status,base_version)"
                     " VALUES('p1','apr_1','wf',?,1)", (status,))
    store.db.commit()


def final(store):
    return store.db.execute("SELECT status FROM proposals WHERE proposal_id='p1'").fetchone()[0]


def test_approved_applies_once(tmp_path):
    store = Store(str(tmp_path))
    seed(store)
    api = FakeApi("approved")
    govern.poll_and_apply(api, store, "2030-01-01T10:00:00+05:30")
    assert final(store) == "applied" and api.applies == 1


def test_crashed_after_apply_recovers_as_applied(tmp_path):
    store = Store(str(tmp_path))
    seed(store)
    api = FakeApi("approved", apply_error="not_approved", apply_detail={"status": "applied"})
    govern.poll_and_apply(api, store, "2030-01-01T10:00:00+05:30")
    assert final(store) == "applied"  # sim says already applied -> no double apply


def test_lapsed(tmp_path):
    store = Store(str(tmp_path))
    seed(store)
    api = FakeApi("approved", apply_error="lapsed")
    govern.poll_and_apply(api, store, "2030-01-01T10:00:00+05:30")
    assert final(store) == "lapsed"


def test_stale_on_external_change(tmp_path):
    store = Store(str(tmp_path))
    seed(store)
    with store.db:
        govern.mark_stale_on_external_change(store, "wf", "2030-01-01T10:00:00+05:30")
    assert final(store) == "stale"


def test_rejected_terminal(tmp_path):
    store = Store(str(tmp_path))
    seed(store)
    api = FakeApi("rejected")
    govern.poll_and_apply(api, store, "2030-01-01T10:00:00+05:30")
    assert final(store) == "rejected" and api.applies == 0
