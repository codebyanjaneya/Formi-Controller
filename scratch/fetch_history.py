"""Download all history chunks from the sim into scratch/history.ndjson (HTTP only)."""
import json
import sys
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8700"
out = sys.argv[2] if len(sys.argv) > 2 else "scratch/history.ndjson"

chunks = json.load(urllib.request.urlopen(f"{BASE}/events/chunks?kind=history"))
print("history chunks:", [c["chunk"] for c in chunks])
with open(out, "w", encoding="utf-8") as f:
    for c in chunks:
        txt = urllib.request.urlopen(f"{BASE}/events/chunks/{c['chunk']}").read().decode()
        f.write(txt if txt.endswith("\n") else txt + "\n")
print("saved", out)
