"""Crash-test invariants (design: README 5.8). Checks PROPERTIES, not exact numbers.

Usage: python scripts/check_invariants.py <SIM_URL> <STATE_DIR>
Exit 0 = all invariants hold.
"""
import json
import os
import sqlite3
import sys
import urllib.request

url, state_dir = sys.argv[1], sys.argv[2]
db = sqlite3.connect(os.path.join(state_dir, "state.db"))
calls = sqlite3.connect(os.path.join(state_dir, "calls.db"))


def get(path):
    return json.load(urllib.request.urlopen(url + path))


failures = []


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(name)


st = get("/sim/state")
check("scenario ran to completion", st["finished"])

# cursor: exactly caught up, never ahead
check("event cursor == sim last_event_id",
      int(db.execute("SELECT value FROM meta WHERE key='last_event_id'").fetchone()[0])
      == st["last_event_id"])

# no approved-but-lost proposal: at scenario end nothing we own is still 'approved'
sim_approvals = get("/approvals")
ours = {r[0]: r[1] for r in db.execute("SELECT approval_id, status FROM proposals")}
stuck = [a for a in sim_approvals if a["status"] == "approved"]
check("no approved-but-never-applied proposal left", not stuck, f"{len(stuck)} stuck")

# our status mirror agrees with the sim's terminal status
mismatch = [a["approval_id"] for a in sim_approvals
            if a["approval_id"] in ours and a["status"] != ours[a["approval_id"]]
            and not (a["status"] == "approved" and ours[a["approval_id"]] == "applied")
            and ours[a["approval_id"]] != "stale"]
check("proposal state machine matches sim", not mismatch, str(mismatch[:5]))

# no double apply: every applied audit row is unique per approval, and every config version
# the sim knows about appears exactly once in our store
dup_applied = db.execute(
    "SELECT ref, COUNT(*) c FROM audit WHERE kind='applied' GROUP BY ref HAVING c>1").fetchall()
check("no proposal applied twice", not dup_applied, str(dup_applied[:3]))
for w in get("/workflows"):
    wid = w["workflow_id"]
    hist = get(f"/workflows/{wid}/config/history")
    ours_v = {r[0] for r in db.execute("SELECT version FROM config_versions WHERE wid=?", (wid,))}
    sim_v = {h["version"] for h in hist} - {1}  # v1 (business_default) emits no event
    missing = sim_v - ours_v
    check(f"config versions complete for {wid}", not missing,
          f"sim {len(sim_v)+1} vs ours {len(ours_v)}; missing {sorted(missing)[:5]}")

# intents hygiene: nothing pending_send, no unhandled duplicate ids
pend = db.execute("SELECT COUNT(*) FROM intents WHERE status='pending_send'").fetchone()[0]
check("no unsent intents left", pend == 0, f"{pend}")
dups = db.execute("SELECT COUNT(*) FROM intents WHERE status='failed' AND "
                  "response LIKE '%duplicate_proposal_id%'").fetchone()[0]
check("no unhandled duplicate_proposal_id", dups == 0, f"{dups}")

# state.db and calls.db consistent: every aggregated dial has its per-call row
agg = db.execute("SELECT COALESCE(SUM(dials),0) FROM agg_calls").fetchone()[0]
nc = calls.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
check("agg_calls dials == calls.db rows", agg == nc, f"{agg} vs {nc}")

lapsed = sum(1 for a in sim_approvals if a["status"] == "lapsed")
print(f"\ninfo: approvals={len(sim_approvals)} lapsed={lapsed} "
      f"versions_total={sum(1 for _ in db.execute('SELECT 1 FROM config_versions'))}")
sys.exit(1 if failures else 0)
