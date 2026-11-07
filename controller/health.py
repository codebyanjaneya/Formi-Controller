"""Loop health (C14): `python -m controller.health [--url SIM_URL]`.

Prints: ingest lag, decisions/hour, credit burn, open incidents, stuck proposals — and
which of these an on-call engineer should be PAGED for vs just see on a dashboard.
"""
import argparse
import json
import os
import sqlite3
import urllib.request


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", default="state")
    ap.add_argument("--url", help="sim URL for live ingest-lag check (optional)")
    a = ap.parse_args()
    db = sqlite3.connect(os.path.join(a.state_dir, "state.db"))
    meta = dict(db.execute("SELECT key, value FROM meta"))
    page = []

    print("== loop health ==")
    our_cursor = int(meta.get("last_event_id", -1))
    if a.url:
        st = json.load(urllib.request.urlopen(a.url + "/sim/state"))
        lag = st["last_event_id"] - our_cursor
        print(f"ingest lag: {lag} events behind the sim"
              f" (cursor {our_cursor} / sim {st['last_event_id']})")
        if lag > 100000:
            page.append(f"ingest lag {lag} events — loop stalled or too slow")
        print(f"credits remaining: {st.get('credits_remaining')}")
    else:
        print(f"ingest cursor: {our_cursor} (pass --url for live lag)")

    last_day = db.execute("SELECT MAX(substr(ts,1,10)) FROM audit").fetchone()[0]
    decisions = db.execute(
        "SELECT COUNT(*) FROM audit WHERE kind LIKE 'intent_%' AND ts LIKE ?",
        ((last_day or "") + "%",)).fetchone()[0]
    print(f"decisions on last sim-day ({last_day}): {decisions} "
          f"(~{decisions/24:.1f}/h)")

    burns = db.execute("SELECT ts, json_extract(details,'$.credits_remaining') FROM audit "
                       "WHERE kind='loop_health' ORDER BY id").fetchall()
    if len(burns) >= 2 and burns[-1][1] is not None and burns[0][1] is not None:
        burn = (burns[0][1] - burns[-1][1]) / max(1, len(burns) - 1)
        print(f"credit burn: {burn:.1f}/sim-day (start {burns[0][1]}, now {burns[-1][1]})")
        start = float(meta.get("starting_credits", 0) or 0)
        if start and burns[-1][1] < 0.2 * start:
            page.append(f"credits below the 20% reserve ({burns[-1][1]}/{start})")

    open_inc = db.execute("SELECT id, wid, metric, slice, detected_ts FROM incidents "
                          "WHERE resolved_ts IS NULL").fetchall()
    print(f"open incidents: {len(open_inc)}")
    for i in open_inc:
        print(f"  inc{i[0]} {i[1]} {i[2]}@{i[3]} since {i[4]}")
    halluc_open = [i for i in open_inc if i[2] == "halluc"]
    if halluc_open:
        page.append(f"open hallucination incident(s): {[i[0] for i in halluc_open]}")

    stuck = db.execute(
        "SELECT proposal_id, wid, status, expires_at FROM proposals WHERE status='pending'"
    ).fetchall()
    print(f"pending proposals: {len(stuck)}")
    failed = db.execute("SELECT COUNT(*) FROM intents WHERE status='failed'").fetchone()[0]
    print(f"failed intents (handled, logged): {failed}")
    pend_send = db.execute("SELECT COUNT(*) FROM intents WHERE status='pending_send'").fetchone()[0]
    if pend_send:
        page.append(f"{pend_send} intents stuck in pending_send — act() not running")

    print("\n== page on ==")
    for p in page or ["(nothing — healthy)"]:
        print(f"  !! {p}")
    print("== do NOT page on (dashboard only) ==")
    print("  - resolved incidents, rejected/expired proposals (normal governance)")
    print("  - 'no healthy alternative' no-action incidents (nothing to do)")
    print("  - failed intents with a handled 4xx (logged, decision engine re-plans)")


if __name__ == "__main__":
    main()
