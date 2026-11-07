"""Ingest speed benchmark against a running sim (public_03_load expected).

Measures our real ingest path (controller.ingest) on history chunks: events/sec
including JSON parse, aggregation, calls.db insert and the state txn.

Usage: python scratch/ingest_bench.py http://127.0.0.1:8701
"""
import shutil
import sys
import time

sys.path.insert(0, ".")
from controller.api import Sim  # noqa: E402
from controller.store import Store  # noqa: E402
from controller import ingest  # noqa: E402

url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8701"
state_dir = "scratch/bench_state"
shutil.rmtree(state_dir, ignore_errors=True)

api = Sim(url)
store = Store(state_dir)
hist = api.list_chunks("history")
nums = [c["chunk"] for c in hist]

# fetch first so network time is excluded from the ingest number (we report both)
t0 = time.time()
sizes = {}
for n in nums:
    sizes[n] = len(api.chunk_lines(n))
fetch_s = time.time() - t0

t0 = time.time()
total = ingest.ingest_chunks(api, store, nums)  # includes re-fetch; conservative
ingest_s = time.time() - t0

print(f"chunks: {len(nums)}, events: {total}")
print(f"fetch-only pass: {sum(sizes.values())/fetch_s:.0f} lines/s")
print(f"full ingest (fetch+parse+aggregate+write): {total/ingest_s:.0f} events/s "
      f"({ingest_s:.1f}s total)")
