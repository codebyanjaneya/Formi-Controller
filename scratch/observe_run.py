"""Passively advance a sim to the end, saving history + live call/config events to ndjson.

Usage: python scratch/observe_run.py [URL] [OUT_PREFIX]
Writes <prefix>_history.ndjson and <prefix>_live.ndjson (calls + non-call events, with sim ts).
"""
import json
import sys
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8700"
prefix = sys.argv[2] if len(sys.argv) > 2 else "scratch/probe03"


def get(path):
    return urllib.request.urlopen(BASE + path, timeout=120).read().decode()


def post(path, body):
    r = urllib.request.Request(BASE + path, method="POST", data=json.dumps(body).encode(),
                               headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=120))


hist = json.loads(get("/events/chunks?kind=history"))
with open(f"{prefix}_history.ndjson", "w", encoding="utf-8") as f:
    for c in hist:
        f.write(get(f"/events/chunks/{c['chunk']}").strip() + "\n")
print("history chunks:", len(hist), flush=True)

st = json.loads(get("/sim/state"))
tick = st["tick_minutes"]  # advance response doesn't echo tick_minutes
ticks = 0
with open(f"{prefix}_live.ndjson", "w", encoding="utf-8") as f:
    while not st["finished"]:
        st = post("/sim/advance", {"minutes": tick})
        ticks += 1
        for c in st.get("new_chunks", []):
            txt = get(f"/events/chunks/{c['chunk']}")
            for line in txt.splitlines():
                if line.strip():
                    f.write(line + "\n")
        if ticks % 96 == 0:
            print("tick", ticks, st["ts"], flush=True)
print("done", ticks, "ticks", st["ts"], flush=True)
