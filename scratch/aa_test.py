"""A/A test of the production winner test (check: false-winner rate).

All history calls carry the SAME real variant; we assign them randomly to 3 fake arms
(1 champion + 2 challengers, 70/15/15 like production) and run controller.experiments.
winner_test. A correct test should declare a winner in <= ~5% of random splits.

Usage: python scratch/aa_test.py [iterations]
"""
import json
import random
import sys

sys.path.insert(0, ".")
from controller.experiments import winner_test  # noqa: E402

iters = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
calls = []  # (connected, engaged) per workflow
by_wf = {}
for line in open("scratch/history.ndjson", encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    ev = json.loads(line)
    if ev["type"] == "call" and ev["connected"]:
        by_wf.setdefault(ev["workflow_id"], []).append(1 if ev["engaged"] else 0)

rng = random.Random(42)
for wid, engs in by_wf.items():
    false_wins = 0
    for _ in range(iters):
        arms = {"champ": [0, 0], "c1": [0, 0], "c2": [0, 0]}
        for e in engs:
            r = rng.random()
            a = "champ" if r < 0.7 else ("c1" if r < 0.85 else "c2")
            arms[a][0] += e
            arms[a][1] += 1
        v = winner_test({k: (x, n) for k, (x, n) in arms.items()}, "champ")
        if v:
            false_wins += 1
    print(f"{wid}: {len(engs)} connected calls, false-winner rate "
          f"{false_wins}/{iters} = {false_wins/iters:.3%}")
