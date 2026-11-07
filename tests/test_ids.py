"""Deterministic proposal ids: same decision -> same id (crash-safe resend); new attempt -> new id."""
import sys

sys.path.insert(0, ".")
from controller.govern import make_proposal_id


def test_same_inputs_same_id():
    a = make_proposal_id("wf", 3, {"allocations.default.voice": {"V2": 1}}, "approval", 1)
    b = make_proposal_id("wf", 3, {"allocations.default.voice": {"V2": 1}}, "approval", 1)
    assert a == b and len(a) == 32


def test_key_order_does_not_matter():
    a = make_proposal_id("wf", 3, {"x": 1, "y": 2}, "approval", 1)
    b = make_proposal_id("wf", 3, {"y": 2, "x": 1}, "approval", 1)
    assert a == b


def test_attempt_and_fields_change_id():
    base = make_proposal_id("wf", 3, {"d": 1}, "approval", 1)
    assert make_proposal_id("wf", 3, {"d": 1}, "approval", 2) != base  # retry = new id
    assert make_proposal_id("wf", 4, {"d": 1}, "approval", 1) != base
    assert make_proposal_id("wf", 3, {"d": 2}, "approval", 1) != base
    assert make_proposal_id("wf", 3, {"d": 1}, "auto", 1) != base
