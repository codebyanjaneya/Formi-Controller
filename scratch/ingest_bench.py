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

def peak_mem_mb():
    import ctypes
    import ctypes.wintypes as wt

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
    k32 = ctypes.windll.kernel32
    k32.GetCurrentProcess.restype = wt.HANDLE
    fn = k32.K32GetProcessMemoryInfo
    fn.argtypes = [wt.HANDLE, ctypes.POINTER(PMC), wt.DWORD]
    fn.restype = wt.BOOL
    pmc = PMC(cb=ctypes.sizeof(PMC))
    if not fn(k32.GetCurrentProcess(), ctypes.byref(pmc), ctypes.sizeof(PMC)):
        raise OSError("K32GetProcessMemoryInfo failed")
    return pmc.PeakWorkingSetSize / 1e6


print(f"chunks: {len(nums)}, events: {total}")
print(f"fetch-only pass: {sum(sizes.values())/fetch_s:.0f} lines/s")
print(f"full ingest (fetch+parse+aggregate+calls.db+state txn): {total/ingest_s:.0f} events/s "
      f"({ingest_s:.1f}s total)")
try:
    print(f"peak working set: {peak_mem_mb():.0f} MB")
except Exception as e:  # non-Windows fallback
    import resource
    print(f"peak RSS: {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024:.0f} MB ({e})")
