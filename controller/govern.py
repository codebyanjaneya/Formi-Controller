"""Governance client: intent log, deterministic proposal ids, send/poll/apply, reconcile.

Flow (design.md section 3-5): decisions write an intent row (pending_send) in the same
transaction as their audit entry; act() sends them; poll() tracks approvals and applies
approved proposals inside their window; reconcile() repairs state after a crash.
"""
import hashlib
import json
import logging
from datetime import datetime

from .api import ApiError
from . import policy as pol

log = logging.getLogger("govern")

TERMINAL = {"rejected", "expired", "applied", "lapsed", "stale"}


def make_proposal_id(wid: str, base_version: int, diff: dict, kind: str, attempt: int) -> str:
    raw = f"{wid}|{base_version}|{json.dumps(diff, sort_keys=True)}|{kind}|{attempt}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def queue_intent(store, now: str, wid: str, kind: str, base_version: int, payload: dict,
                 diff: dict, attempt: int = 1) -> str:
    """Write the intent row (BEFORE any network send). Caller commits the transaction."""
    pid = make_proposal_id(wid, base_version, diff, kind, attempt)
    payload = dict(payload, proposal_id=pid)
    store.db.execute(
        "INSERT OR IGNORE INTO intents(proposal_id,wid,kind,attempt,base_version,payload,status,created_ts)"
        " VALUES(?,?,?,?,?,?,'pending_send',?)",
        (pid, wid, kind, attempt, base_version, json.dumps(payload), now))
    store.audit(now, wid, f"intent_{kind}", pid, {"base_version": base_version, "diff": diff,
                                                  "attempt": attempt})
    return pid


def act(api, store, now: str):
    """Send every pending intent; outcome goes to the same row."""
    rows = store.db.execute(
        "SELECT proposal_id, wid, kind, payload FROM intents WHERE status='pending_send'").fetchall()
    for pid, wid, kind, payload in rows:
        body = json.loads(payload)
        try:
            if kind == "approval":
                r = api.post_approval(body)
                with store.db:
                    store.db.execute("UPDATE intents SET status='acked', response=? WHERE proposal_id=?",
                                     (json.dumps(r), pid))
                    store.db.execute(
                        "INSERT OR REPLACE INTO proposals(proposal_id,approval_id,wid,status,base_version,"
                        "expires_at,apply_by,reasons,decided_ts) VALUES(?,?,?,?,?,?,?,?,?)",
                        (pid, r["approval_id"], wid, r.get("status", "pending"), body["base_version"],
                         r.get("expires_at"), None, None, None))
                    store.audit(now, wid, "proposal_sent", r["approval_id"], {"proposal_id": pid})
            elif kind == "auto":
                r = api.put_config(wid, body)
                with store.db:
                    store.db.execute("UPDATE intents SET status='acked', response=? WHERE proposal_id=?",
                                     (json.dumps(r), pid))
                    store.audit(now, wid, "auto_applied", pid, {"response": r})
        except ApiError as e:
            if e.error == "duplicate_proposal_id":
                # crash happened between send and ack last time: the sim has it; recover state below
                with store.db:
                    store.db.execute("UPDATE intents SET status='sent' WHERE proposal_id=?", (pid,))
                continue
            with store.db:
                store.db.execute("UPDATE intents SET status='failed', response=? WHERE proposal_id=?",
                                 (json.dumps({"error": e.error, "detail": e.detail}), pid))
                store.audit(now, wid, "intent_failed", pid, {"error": e.error, "detail": e.detail})
            log.warning("intent %s failed: %s %s", pid, e.error, e.detail)


def poll_and_apply(api, store, now: str):
    """Track pending proposals; apply approved ones immediately (inside apply window)."""
    rows = store.db.execute(
        "SELECT proposal_id, approval_id, wid, status FROM proposals "
        "WHERE status IN ('pending','approved')").fetchall()
    for pid, aid, wid, status in rows:
        ap = api.get_approval(aid)
        st = ap["status"]
        if st != status:
            with store.db:
                store.db.execute("UPDATE proposals SET status=?, reasons=?, decided_ts=? WHERE proposal_id=?",
                                 (st, json.dumps(ap.get("reasons")), ap.get("decided_at"), pid))
                store.audit(now, wid, "proposal_" + st, aid, {"reasons": ap.get("reasons")})
        if st == "approved":
            try:
                r = api.apply(wid, aid)
                with store.db:
                    store.db.execute("UPDATE proposals SET status='applied' WHERE proposal_id=?", (pid,))
                    store.audit(now, wid, "applied", aid, {"version": r.get("version"),
                                                           "changed_dims": r.get("changed_dims")})
            except ApiError as e:
                new = {"not_approved": None, "stale_base_version": "stale"}.get(e.error)
                if e.error == "not_approved" and isinstance(e.detail, dict) \
                        and e.detail.get("status") == "applied":
                    new = "applied"  # crash between apply and ack last time
                if e.status == 410:
                    new = "lapsed"
                if new:
                    with store.db:
                        store.db.execute("UPDATE proposals SET status=? WHERE proposal_id=?", (new, pid))
                        store.audit(now, wid, "apply_" + new, aid, {"error": e.error})
                else:
                    log.warning("apply %s: %s %s", aid, e.error, e.detail)


def mark_stale_on_external_change(store, wid: str, now: str):
    """A config_changed by someone else invalidates our pending proposals for that workflow."""
    rows = store.db.execute(
        "SELECT proposal_id FROM proposals WHERE wid=? AND status IN ('pending','approved')",
        (wid,)).fetchall()
    for (pid,) in rows:
        store.db.execute("UPDATE proposals SET status='stale' WHERE proposal_id=?", (pid,))
        store.audit(now, wid, "proposal_stale", pid, {"reason": "external config change"})


def reconcile(api, store, now: str):
    """Startup: repair intent/proposal state against the sim's truth."""
    # intents that were sent (or unknown) but never acked
    rows = store.db.execute(
        "SELECT proposal_id, wid, kind FROM intents WHERE status IN ('pending_send','sent')").fetchall()
    by_wid = {}
    for pid, wid, kind in rows:
        if kind == "approval":
            if wid not in by_wid:
                by_wid[wid] = {a.get("proposal_id"): a for a in api.list_approvals(wid=wid)}
            ap = by_wid[wid].get(pid)
            if ap:  # it did reach the sim before the crash
                with store.db:
                    store.db.execute("UPDATE intents SET status='acked', response=? WHERE proposal_id=?",
                                     (json.dumps(ap), pid))
                    store.db.execute(
                        "INSERT OR REPLACE INTO proposals(proposal_id,approval_id,wid,status,base_version,"
                        "expires_at,apply_by,reasons,decided_ts) VALUES(?,?,?,?,?,?,?,?,?)",
                        (pid, ap["approval_id"], wid, ap["status"], ap.get("base_version"),
                         ap.get("expires_at"), None, json.dumps(ap.get("reasons")), ap.get("decided_at")))
                    store.audit(now, wid, "reconciled", pid, {"found": ap["status"]})
            # else: still pending_send; act() will (re)send the same deterministic id.
        elif kind == "auto":
            # Check config history for a version carrying our proposal_id; else mark failed
            # (we never blind-resend a PUT — the decision engine will re-decide on fresh data).
            found = None
            try:
                for v in api.config_history(wid):
                    if isinstance(v, dict) and v.get("proposal_id") == pid:
                        found = v
                        break
            except ApiError:
                pass
            with store.db:
                if found:
                    store.db.execute("UPDATE intents SET status='acked', response=? WHERE proposal_id=?",
                                     (json.dumps(found), pid))
                else:
                    store.db.execute("UPDATE intents SET status='failed', response=? WHERE proposal_id=?",
                                     (json.dumps({"error": "unconfirmed_after_crash"}), pid))
                store.audit(now, wid, "reconciled_auto", pid, {"found": bool(found)})
    # refresh all non-terminal proposals
    poll_and_apply(api, store, now)
