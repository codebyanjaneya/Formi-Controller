"""Audit CLI (C12).

  python -m controller.why why --workflow nw_renewal [--since 2027-01-05]
      every decision/audit row for the workflow, in order, human-readable.
  python -m controller.why heard --person nw_renewal:p0001234 [--day 2027-01-06]
      what that person heard on each call, under which config version, and why
      that version existed (who changed it, which approval).
"""
import argparse
import json
import os
import sqlite3


def open_dbs(state_dir):
    state = sqlite3.connect(os.path.join(state_dir, "state.db"))
    calls = sqlite3.connect(os.path.join(state_dir, "calls.db"))
    return state, calls


def cmd_why(a):
    db, _ = open_dbs(a.state_dir)
    q = "SELECT ts, kind, ref, details FROM audit WHERE wid=?"
    args = [a.workflow]
    if a.since:
        q += " AND ts>=?"
        args.append(a.since)
    for ts, kind, ref, details in db.execute(q + " ORDER BY id", args):
        print(f"{ts}  {kind:24s} {ref or '':12s} {details}")


def cmd_heard(a):
    db, calls = open_dbs(a.state_dir)
    q = ("SELECT ts, wid, cohort_id, config_version, welcome, voice, caller_id, prompt,"
         " connected, engaged, disposition FROM calls WHERE person_id=?")
    args = [a.person]
    if a.day:
        q += " AND substr(ts,1,10)=?"
        args.append(a.day)
    rows = calls.execute(q + " ORDER BY ts", args).fetchall()
    if not rows:
        print("no calls found")
        return
    for ts, wid, cohort, ver, w, v, d, p, conn, eng, disp in rows:
        print(f"\n{ts}  {wid}  cohort={cohort}  config v{ver}")
        print(f"  heard: welcome={w} voice={v} caller_id={d} prompt={p}"
              f"  -> {'connected' if conn else 'no answer'}"
              f"{', engaged' if eng else ''} ({disp})")
        cv = db.execute("SELECT actor, changed_dims, ts FROM config_versions WHERE wid=? AND version=?",
                        (wid, ver)).fetchone()
        if cv:
            print(f"  why this config: v{ver} set by {cv[0]} at {cv[2]} (changed: {cv[1]})")
        ap = db.execute("SELECT ref, details FROM audit WHERE wid=? AND kind='applied'"
                        " AND json_extract(details,'$.version')=?", (wid, ver)).fetchone()
        if ap:
            print(f"  approval: {ap[0]} {ap[1]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", default="state")
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("why")
    w.add_argument("--workflow", required=True)
    w.add_argument("--since")
    h = sub.add_parser("heard")
    h.add_argument("--person", required=True)
    h.add_argument("--day")
    a = ap.parse_args()
    {"why": cmd_why, "heard": cmd_heard}[a.cmd](a)


if __name__ == "__main__":
    main()
