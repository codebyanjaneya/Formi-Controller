"""Workflow policy, read from the API at runtime. Nothing about any workflow is hardcoded.

Also holds our own 'client preferences' caution layer (D011): voluntary limits that are
never looser than the policy API's own governance block.
"""
import json
import logging
from datetime import datetime, timedelta

log = logging.getLogger("policy")

# Our voluntary caution settings per workflow-id prefix (see docs/design.md, D011).
# These only ever TIGHTEN what the policy API allows.
CLIENT_PREFERENCES = {
    "ks_": {"max_requests_per_day": 2, "earliest_proposal_hour": 11},
}

# Dims a customer hears: ALWAYS routed via approval, never auto-applied (D009).
AUDIBLE_DIMS = {"welcome_message", "voice", "prompt_version"}


def refresh(api, store, ts: str):
    for w in api.workflows():
        store.db.execute(
            "INSERT INTO workflows(wid,policy,fetched_at) VALUES(?,?,?) "
            "ON CONFLICT(wid) DO UPDATE SET policy=excluded.policy, fetched_at=excluded.fetched_at",
            (w["workflow_id"], json.dumps(w), ts))
    store.db.commit()


def get(store, wid: str) -> dict:
    row = store.db.execute("SELECT policy FROM workflows WHERE wid=?", (wid,)).fetchone()
    return json.loads(row[0]) if row else {}


def all_wids(store) -> list[str]:
    return [r[0] for r in store.db.execute("SELECT wid FROM workflows").fetchall()]


def route(policy: dict, changed_dims: set[str], tv_shift: float) -> str:
    """'auto' or 'approval' for a change touching changed_dims with max TV shift tv_shift."""
    if changed_dims & AUDIBLE_DIMS:
        return "approval"
    auto = policy.get("governance", {}).get("auto_apply", {})
    if (auto.get("enabled") and changed_dims <= set(auto.get("allowed_dims", []))
            and tv_shift <= auto.get("max_shift", 0)):
        return "auto"
    return "approval"


def preferences(wid: str) -> dict:
    for prefix, prefs in CLIENT_PREFERENCES.items():
        if wid.startswith(prefix):
            return prefs
    return {}


def good_send_time(policy: dict, now: datetime) -> datetime | None:
    """Earliest time >= now at which a proposal should be sent so the approver can both
    see it (approver_hours) and decide it (max latency) before TTL. Returns None if now is fine."""
    gov = policy.get("governance", {})
    start_h, end_h = gov.get("approver_hours", [0, 24])
    max_lat_min = (gov.get("approver_latency_minutes") or [0, 240])[1]
    pref_h = max(start_h, 0)
    # decision must land before the window closes: send no later than end - latency
    latest_ok = end_h - max_lat_min / 60.0
    h = now.hour + now.minute / 60.0
    if pref_h <= h <= latest_ok:
        return None  # send now
    target = now.replace(minute=0, second=0, microsecond=0)
    if h > latest_ok:
        target += timedelta(days=1)
    return target.replace(hour=pref_h)


def expires_in_hours(policy: dict) -> int:
    return int(policy.get("governance", {}).get("proposal_ttl_hours", 24))


def requests_in_last_24h(store, wid: str, now_iso: str) -> int:
    cutoff = (datetime.fromisoformat(now_iso) - timedelta(hours=24)).isoformat()
    return store.db.execute(
        "SELECT COUNT(*) FROM intents WHERE wid=? AND kind='approval' AND status IN ('sent','acked')"
        " AND created_ts >= ?", (wid, cutoff)).fetchone()[0]


def request_budget_left(store, policy: dict, wid: str, now_iso: str) -> int:
    cap = policy.get("governance", {}).get("max_requests_per_24h", 1)
    pref_cap = preferences(wid).get("max_requests_per_day")
    if pref_cap is not None:
        cap = min(cap, pref_cap)
    return cap - requests_in_last_24h(store, wid, now_iso)
