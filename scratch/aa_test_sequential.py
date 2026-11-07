"""Sequential A/A test with the REAL stopping rule (replayed tick by tick).

History calls (one true variant) are replayed in 15-min ticks and randomly assigned to
3 arms (70/15/15). Two rules are measured:
  every-tick : test at every tick once min-n(10pp) reached (the naive stopping rule)
  two-look   : test ONLY at min-n(10pp) and min-n(5pp), alpha split across looks
               (the production rule in controller.experiments._judge)

Usage: python scratch/aa_test_sequential.py [iterations]
"""
import json
import random
import sys
from collections import defaultdict

sys.path.insert(0, ".")
from controller.experiments import winner_test, n_per_arm, ALPHA, LOOKS  # noqa: E402

iters = int(sys.argv[1]) if len(sys.argv) > 1 else 500
by_wf = defaultdict(list)  # wf -> [(tick_key, engaged)]
for line in open("scratch/history.ndjson", encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    ev = json.loads(line)
    if ev["type"] == "call" and ev["connected"]:
        tick = ev["ts"][:14] + ("00" if ev["ts"][14] < "3" else "30")  # 30-min buckets ok
        by_wf[ev["workflow_id"]].append((tick, 1 if ev["engaged"] else 0))

rng = random.Random(7)
K = 2  # challengers
for wid, calls in sorted(by_wf.items()):
    calls.sort()
    base = sum(e for _, e in calls) / len(calls)
    n10 = n_per_arm(base, 0.10, ALPHA / (K * LOOKS))
    n5 = n_per_arm(base, 0.05, ALPHA / (K * LOOKS))
    fw_everytick = fw_twolook = 0
    for _ in range(iters):
        arms = {"champ": [0, 0], "c1": [0, 0], "c2": [0, 0]}
        declared_et = False
        look = 0
        declared_tl = False
        cur_tick = None
        for tick, e in calls:
            r = rng.random()
            a = "champ" if r < 0.7 else ("c1" if r < 0.85 else "c2")
            arms[a][0] += e
            arms[a][1] += 1
            if tick != cur_tick:
                cur_tick = tick
                snapshot = {k: (x, n) for k, (x, n) in arms.items()}
                ns = [n for _, n in snapshot.values()]
                if not declared_et and min(ns) >= n10:
                    if winner_test(snapshot, "champ", alpha=ALPHA):
                        declared_et = True
                if not declared_tl:
                    if look == 0 and min(ns) >= n10:
                        if winner_test(snapshot, "champ", alpha=ALPHA / LOOKS):
                            declared_tl = True
                        look = 1
                    elif look == 1 and min(ns) >= n5:
                        if winner_test(snapshot, "champ", alpha=ALPHA / LOOKS):
                            declared_tl = True
                        look = 2  # no further looks
        fw_everytick += declared_et
        fw_twolook += declared_tl
    print(f"{wid}: n10={n10} n5={n5} | every-tick false winners {fw_everytick}/{iters}"
          f" = {fw_everytick/iters:.1%} | two-look {fw_twolook}/{iters} = {fw_twolook/iters:.1%}")
