"""One real governance round-trip using the controller's own modules (check 2+3).

- approval path: small caller_id change on nw_kyc (auto_apply disabled there)
- auto path:     small caller_id shift on nw_renewal (allowed_dims includes caller_id)
Then prints intent/proposal/audit rows and the REAL /config/history shape.
"""
import json
import sys

sys.path.insert(0, ".")
from controller.api import Sim
from controller.store import Store
from controller import govern, policy, ingest

api = Sim("http://127.0.0.1:8702")
store = Store("scratch/chk_state")
st = api.state()
now = st["ts"]
policy.refresh(api, store, now)

# --- approval path (nw_kyc: auto disabled) ---
cur = api.get_config("nw_kyc")
cfg = json.loads(json.dumps(cur["config"]))
alloc = cfg["allocations"]["default"]
kyc_policy = policy.get(store, "nw_kyc")
options = kyc_policy["options"]["caller_id"]
old = dict(alloc["caller_id"])
alloc["caller_id"] = {options[0]: 0.8, options[1]: 0.2}
diff = {"allocations.default.caller_id": alloc["caller_id"]}
route = policy.route(kyc_policy, {"caller_id"}, tv_shift=0.2)
print("route for kyc caller_id:", route)
payload = {"workflow_id": "nw_kyc", "base_version": cur["version"], "proposed_config": cfg,
           "change_summary": f"governance check: caller_id {old} -> {alloc['caller_id']}",
           "diff": diff, "affected_leads": store.db.execute(
               "SELECT COUNT(*) FROM leads WHERE wid='nw_kyc' AND done=0").fetchone()[0],
           "dry_run": {"note": "mechanical round-trip check, allocation shift 0.2 TV"},
           "impact_score": 0.05, "rationale": "verify approval path end to end",
           "expires_in_hours": policy.expires_in_hours(kyc_policy)}
with store.db:
    pid = govern.queue_intent(store, now, "nw_kyc", "approval", cur["version"], payload, diff)
govern.act(api, store, now)
print("intent after act:", store.db.execute(
    "SELECT status FROM intents WHERE proposal_id=?", (pid,)).fetchone())

# --- auto path (nw_renewal: caller_id in allowed_dims, max_shift 0.5) ---
cur_r = api.get_config("nw_renewal")
cfg_r = json.loads(json.dumps(cur_r["config"]))
ren_policy = policy.get(store, "nw_renewal")
ropts = ren_policy["options"]["caller_id"]
cfg_r["allocations"]["default"]["caller_id"] = {ropts[0]: 0.6, ropts[1]: 0.4}
rdiff = {"allocations.default.caller_id": cfg_r["allocations"]["default"]["caller_id"]}
print("route for renewal caller_id:", policy.route(ren_policy, {"caller_id"}, tv_shift=0.1))
auto_payload = {"workflow_id": "nw_renewal", "base_version": cur_r["version"],
                "proposed_config": cfg_r, "rationale": "governance check: auto-apply path"}
with store.db:
    pid2 = govern.queue_intent(store, now, "nw_renewal", "auto", cur_r["version"], auto_payload, rdiff)
govern.act(api, store, now)
print("auto intent:", store.db.execute(
    "SELECT status, response FROM intents WHERE proposal_id=?", (pid2,)).fetchone())

# --- advance until the approval is decided and applied ---
for i in range(60):
    st = api.advance(60)
    now = st["ts"]
    ingest.ingest_chunks(api, store, ingest.new_chunk_numbers(api, store, st))
    govern.poll_and_apply(api, store, now)
    row = store.db.execute("SELECT status FROM proposals WHERE proposal_id=?", (pid,)).fetchone()
    if row and row[0] in govern.TERMINAL:
        print("proposal terminal state:", row[0], "at", now)
        break

print("\n--- proposals table ---")
for r in store.db.execute("SELECT proposal_id, approval_id, wid, status FROM proposals"):
    print(r)
print("\n--- audit (governance kinds) ---")
for r in store.db.execute("SELECT ts, wid, kind, ref FROM audit WHERE kind NOT IN "
                          "('config_changed','approval_decided') ORDER BY id"):
    print(r)
print("\n--- REAL /config/history shape (nw_renewal) ---")
h = api.config_history("nw_renewal")
print(type(h), json.dumps(h, indent=1)[:1500])
