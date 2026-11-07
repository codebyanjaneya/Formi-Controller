"""Event ingestion: chunk -> in-memory aggregation -> one batched transaction per chunk.

The cursor (last_chunk, last_event_id) commits WITH the aggregates, so a crash can only
cause a whole chunk to be re-read, and calls.db's INSERT OR IGNORE on event_id plus the
monotonic last_event_id filter make re-reads harmless.
"""
import json
import logging
from collections import defaultdict

log = logging.getLogger("ingest")


def ingest_chunks(api, store, chunk_numbers: list[int]) -> int:
    """Process the given chunk numbers in order. Returns events processed."""
    last_event = int(store.get_meta("last_event_id", -1))
    total = 0
    for n in chunk_numbers:
        lines = api.chunk_lines(n)
        total += _ingest_one(store, n, lines, last_event)
        last_event = int(store.get_meta("last_event_id", -1))
    return total


def new_chunk_numbers(api, store, advance_result: dict | None = None) -> list[int]:
    """Chunk numbers we have not processed yet. Uses the advance response when given,
    else (startup) lists from the API — both restart-safe because the cursor decides."""
    last_chunk = int(store.get_meta("last_chunk", -1))
    if advance_result is not None:
        return [c["chunk"] for c in advance_result.get("new_chunks", []) if c["chunk"] > last_chunk]
    return [c["chunk"] for c in api.list_chunks("events", after=max(last_chunk, 0))
            if c["chunk"] > last_chunk]


def _ingest_one(store, chunk_no: int, lines: list[str], last_event: int) -> int:
    agg = defaultdict(lambda: [0, 0, 0, 0, 0, 0.0])  # key -> dials, conn, eng, halluc, adher_lo, adher_sum
    call_rows, lead_rows, camp_rows, cfg_rows, done_leads = [], [], [], [], []
    audits = []
    max_event = last_event
    n_events = 0

    for line in lines:
        if not line.strip():
            continue
        ev = json.loads(line)
        eid = ev["event_id"]
        if eid <= last_event:
            continue
        max_event = max(max_event, eid)
        n_events += 1
        t = ev["type"]
        if t == "call":
            wid = ev["workflow_id"]
            v = ev["variant"]
            qa = ev.get("qa") or {}
            conn = 1 if ev["connected"] else 0
            eng = 1 if (conn and ev.get("engaged")) else 0
            hal = 1 if (conn and qa.get("hallucination_flag")) else 0
            adher = qa.get("flow_adherence")
            key = (wid, ev["ts"][:13], ev["config_version"], ev.get("cohort_id", "default"),
                   v["welcome_message"], v["voice"], v["caller_id"], v["prompt_version"])
            a = agg[key]
            a[0] += 1
            a[1] += conn
            a[2] += eng
            a[3] += hal
            if conn and adher is not None:
                a[4] += 1 if adher < 0.8 else 0
                a[5] += adher
            call_rows.append((eid, ev["ts"], wid, ev["campaign_id"], ev.get("person_id"),
                              ev.get("lead_id"), ev.get("attempt_no"), ev.get("cohort_id"),
                              ev["config_version"], v["welcome_message"], v["voice"],
                              v["caller_id"], v["prompt_version"], conn, eng,
                              ev.get("disposition"), hal, adher))
            if eng:
                done_leads.append((ev.get("lead_id"),))
        elif t == "lead":
            f = ev.get("features", {})
            lead_rows.append((ev["lead_id"], ev["workflow_id"], ev["person_id"], ev["campaign_id"],
                              f.get("lang"), f.get("city_tier"), f.get("age_band"), f.get("value_band")))
        elif t == "campaign_created":
            camp_rows.append((ev["campaign_id"], ev["workflow_id"], ev["ts"], ev.get("leads"),
                              ev.get("config_version_at_creation")))
        elif t == "config_changed":
            cfg_rows.append((ev["workflow_id"], ev["version"], ev.get("actor"),
                             json.dumps(ev.get("changed_dims", [])), ev["ts"], None))
            audits.append((ev["ts"], ev["workflow_id"], "config_changed",
                           f"v{ev['version']}", {"actor": ev.get("actor"),
                                                 "changed_dims": ev.get("changed_dims"),
                                                 "proposal_id": ev.get("proposal_id"),
                                                 "approval_id": ev.get("approval_id")}))
        elif t == "approval_decided":
            audits.append((ev["ts"], ev["workflow_id"], "approval_decided", ev["approval_id"],
                           {"status": ev.get("status"), "reasons": ev.get("reasons")}))

    # calls.db first (idempotent via PK event_id); then state+cursor in ONE txn.
    if call_rows:
        store.calls.executemany(
            "INSERT OR IGNORE INTO calls VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", call_rows)
        store.calls.commit()

    db = store.db
    with db:  # single transaction
        if lead_rows:
            db.executemany("INSERT OR IGNORE INTO leads(lead_id,wid,person_id,campaign_id,"
                           "lang,city_tier,age_band,value_band) VALUES(?,?,?,?,?,?,?,?)", lead_rows)
        if camp_rows:
            db.executemany("INSERT OR IGNORE INTO campaigns VALUES(?,?,?,?,?)", camp_rows)
        if cfg_rows:
            db.executemany("INSERT OR IGNORE INTO config_versions(wid,version,actor,changed_dims,ts,config)"
                           " VALUES(?,?,?,?,?,?)", cfg_rows)
        if done_leads:
            db.executemany("UPDATE leads SET done=1 WHERE lead_id=?", done_leads)
        if agg:
            db.executemany(
                "INSERT INTO agg_calls VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT DO UPDATE SET dials=dials+excluded.dials,"
                "connected=connected+excluded.connected, engaged=engaged+excluded.engaged,"
                "halluc=halluc+excluded.halluc, adher_lo=adher_lo+excluded.adher_lo,"
                "adher_sum=adher_sum+excluded.adher_sum",
                [k + tuple(v) for k, v in agg.items()])
        for a in audits:
            store.audit(a[0], a[1], a[2], a[3], a[4])
        store.set_meta("last_chunk", chunk_no)
        store.set_meta("last_event_id", max_event)
    return n_events


def bootstrap_history(api, store):
    """First start: ingest history chunks and build hour-matched baselines."""
    hist = api.list_chunks("history")
    nums = [c["chunk"] for c in hist]
    n = ingest_chunks(api, store, nums)
    log.info("history bootstrap: %d chunks, %d events", len(nums), n)
    _build_baselines(store)


def _build_baselines(store):
    """Hour-matched baselines per workflow (aggregate) and per caller_id slice, from history."""
    db = store.db
    rows = db.execute(
        "SELECT wid, caller_id, CAST(substr(hour_ts,12,2) AS INT) h,"
        " SUM(dials), SUM(connected), SUM(engaged), SUM(halluc) FROM agg_calls"
        " GROUP BY wid, caller_id, h").fetchall()
    per_wf = defaultdict(lambda: [0, 0, 0, 0])
    out = []
    for wid, cid, h, dials, conn, eng, hal in rows:
        out.append((wid, "pickup", f"caller_id={cid}", h, conn / dials if dials else 0, dials))
        k = (wid, h)
        per_wf[k][0] += dials
        per_wf[k][1] += conn
        per_wf[k][2] += eng
        per_wf[k][3] += hal
    for (wid, h), (dials, conn, eng, hal) in per_wf.items():
        out.append((wid, "pickup", "all", h, conn / dials if dials else 0, dials))
        if conn:
            out.append((wid, "engagement", "all", h, eng / conn, conn))
            out.append((wid, "halluc", "all", h, hal / conn, conn))
    with db:
        db.executemany("INSERT OR REPLACE INTO baselines VALUES(?,?,?,?,?,?)", out)
