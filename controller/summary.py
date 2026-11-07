"""Minimal supervisor view (C11): `python -m controller.summary [--day 2027-01-06]`.

Per workflow: what changed (actor, dims, via auto or approval), what is being tested,
what is waiting on the approver, incidents and the actions taken. This answers the
"tell me what changed" / weekly-summary requests without a UI: run it for each day.
"""
import argparse
import json
import os
import sqlite3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", default="state")
    ap.add_argument("--day", help="YYYY-MM-DD (default: every day in the store)")
    a = ap.parse_args()
    db = sqlite3.connect(os.path.join(a.state_dir, "state.db"))
    like = (a.day or "") + "%"

    wids = [r[0] for r in db.execute("SELECT wid FROM workflows")]
    for wid in wids:
        print(f"\n=== {wid} ===")
        print("-- config changes" + (f" on {a.day}" if a.day else "") + " --")
        rows = db.execute(
            "SELECT version, actor, changed_dims, ts FROM config_versions WHERE wid=? AND ts LIKE ?"
            " ORDER BY version", (wid, like)).fetchall()
        for v, actor, dims, ts in rows:
            via = {"controller_auto": "auto-applied", "controller_approved": "approved",
                   "supervisor": "SUPERVISOR EDIT", "business_default": "initial"}.get(actor, actor)
            reason = db.execute(
                "SELECT json_extract(i.payload,'$.rationale') FROM audit a JOIN intents i ON "
                "json_extract(a.details,'$.proposal_id')=i.proposal_id WHERE a.wid=? AND "
                "a.kind='config_changed' AND a.ref=?", (wid, f"v{v}")).fetchone()
            print(f"  v{v} {ts} [{via}] dims={dims}")
            if reason and reason[0]:
                print(f"      reason: {reason[0][:160]}")
        if not rows:
            print("  (none)")

        print("-- experiments --")
        for r in db.execute("SELECT exp_id, dimension, status, winner FROM experiments WHERE wid=?",
                            (wid,)):
            print(f"  {r[0]}: dim={r[1]} status={r[2]}" + (f" winner={r[3]}" if r[3] else ""))

        print("-- waiting on approver --")
        pend = db.execute("SELECT approval_id, status, expires_at FROM proposals WHERE wid=? AND "
                          "status IN ('pending','approved')", (wid,)).fetchall()
        for r in pend:
            print(f"  {r[0]}: {r[1]} (expires {r[2]})")
        if not pend:
            print("  (none)")

        print("-- incidents --")
        incs = db.execute(
            "SELECT id, metric, slice, detected_ts, resolved_ts, action FROM incidents WHERE wid=?"
            " AND (detected_ts LIKE ? OR resolved_ts LIKE ?)", (wid, like, like)).fetchall()
        shown = 0
        for iid, metric, slice_, det, res, act in incs:
            action = json.loads(act or "{}")
            kind = action.get("kind", "no action")
            print(f"  inc{iid} {metric}@{slice_} detected {det} "
                  f"{'resolved ' + res if res else 'OPEN'} action={kind}")
            shown += 1
        if not shown:
            print("  (none)")


if __name__ == "__main__":
    main()
