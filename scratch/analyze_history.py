"""Step-5 analysis of sim history (HTTP-downloaded ndjson). Prints markdown tables.

Usage: python scratch/analyze_history.py scratch/history.ndjson
"""
import json
import math
import sys
from collections import Counter, defaultdict

FEATS = ["lang", "age_band", "city_tier", "value_band"]
Z_A, Z_B = 1.959964, 0.841621  # alpha=0.05 two-sided, power=0.80


def n_per_arm(p1, delta):
    p2 = min(max(p1 + delta, 0.0001), 0.9999)
    pbar = (p1 + p2) / 2
    num = (Z_A * math.sqrt(2 * pbar * (1 - pbar)) + Z_B * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2
    return math.ceil(num / delta**2)


def ztest(x1, n1, x2, n2):
    """Two-proportion z-test p-value (two-sided)."""
    if n1 == 0 or n2 == 0:
        return 1.0
    p1, p2 = x1 / n1, x2 / n2
    p = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0:
        return 1.0
    z = abs(p1 - p2) / se
    return math.erfc(z / math.sqrt(2))


def main(path):
    lead_feat = {}  # lead_id -> features
    lead_person = {}  # lead_id -> person_id
    campaigns = defaultdict(list)  # wf -> [leads count]
    person_camps = defaultdict(lambda: defaultdict(set))  # wf -> person -> campaigns
    calls = []  # (wf, lead_id, hour, caller_id, connected, engaged, day)
    variants = defaultdict(Counter)  # dim -> Counter
    days = defaultdict(set)

    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        ev = json.loads(line)
        t = ev["type"]
        if t == "lead":
            lead_feat[ev["lead_id"]] = ev["features"]
            lead_person[ev["lead_id"]] = ev["person_id"]
            person_camps[ev["workflow_id"]][ev["person_id"]].add(ev["campaign_id"])
        elif t == "campaign_created":
            campaigns[ev["workflow_id"]].append(ev["leads"])
        elif t == "call":
            wf = ev["workflow_id"]
            day, hour = ev["ts"][:10], int(ev["ts"][11:13])
            days[wf].add(day)
            calls.append((wf, ev["lead_id"], hour, ev["variant"]["caller_id"], ev["connected"], ev["engaged"], day))
            for d, v in ev["variant"].items():
                variants[d][v] += 1

    wfs = sorted(days)
    print("## 1. Volumes per workflow (history window)\n")
    print("| workflow | days | dials/day | connected/day | pickup | engagement (of connected) | leads/campaign | campaigns |")
    print("|---|---|---|---|---|---|---|---|")
    stats = {}
    for wf in wfs:
        cw = [c for c in calls if c[0] == wf]
        nd = len(days[wf])
        dials, conn = len(cw), sum(1 for c in cw if c[4])
        eng = sum(1 for c in cw if c[5])
        stats[wf] = dict(nd=nd, dials=dials, conn=conn, eng=eng)
        lc = campaigns[wf]
        print(f"| {wf} | {nd} | {dials/nd:.0f} | {conn/nd:.0f} | {conn/dials:.3f} | {eng/conn:.3f} | "
              f"{sum(lc)/len(lc):.0f} | {len(lc)} |")

    print("\n## 2. Returning persons per workflow\n")
    print("| workflow | persons | in >1 campaign | share |")
    print("|---|---|---|---|")
    for wf in wfs:
        pc = person_camps[wf]
        rep = sum(1 for s in pc.values() if len(s) > 1)
        print(f"| {wf} | {len(pc)} | {rep} | {rep/len(pc):.2f} |")

    print("\n## 3. Variant diversity in history\n")
    for d, c in variants.items():
        print(f"- **{d}**: {dict(c)}")

    def agg(keyfn):
        out = defaultdict(lambda: [0, 0, 0])  # key -> [dials, conn, eng]
        for c in calls:
            k = keyfn(c)
            if k is None:
                continue
            a = out[k]
            a[0] += 1
            a[1] += c[4]
            a[2] += c[5]
        return out

    print("\n## 4. Breakdowns (per workflow x feature value): dials, pickup, engagement\n")
    sig_notes = []
    for dim in FEATS + ["hour", "caller_id"]:
        if dim == "hour":
            keyfn = lambda c: (c[0], c[2])
        elif dim == "caller_id":
            keyfn = lambda c: (c[0], c[3])
        else:
            keyfn = lambda c, d=dim: (c[0], lead_feat.get(c[1], {}).get(d))
        out = agg(keyfn)
        print(f"\n### by {dim}\n")
        print("| workflow | value | dials | pickup | engagement |")
        print("|---|---|---|---|---|")
        for (wf, val), (d, cn, e) in sorted(out.items()):
            print(f"| {wf} | {val} | {d} | {cn/d:.3f} | {(e/cn if cn else 0):.3f} |")
        # significance: best vs worst engagement value within each wf (min 200 connected)
        if dim in FEATS:
            for wf in wfs:
                vals = {v: x for (w, v), x in out.items() if w == wf and x[1] >= 200}
                if len(vals) < 2:
                    continue
                rates = {v: x[2] / x[1] for v, x in vals.items()}
                hi, lo = max(rates, key=rates.get), min(rates, key=rates.get)
                p = ztest(vals[hi][2], vals[hi][1], vals[lo][2], vals[lo][1])
                sig_notes.append((wf, dim, hi, rates[hi], lo, rates[lo], p))

    print("\n## 5. Which feature differences are statistically supported (engagement, best vs worst value)\n")
    print("| workflow | feature | best | rate | worst | rate | p-value | supported (p<0.01)? |")
    print("|---|---|---|---|---|---|---|---|")
    for wf, dim, hi, rh, lo, rl, p in sorted(sig_notes, key=lambda x: x[6]):
        print(f"| {wf} | {dim} | {hi} | {rh:.3f} | {lo} | {rl:.3f} | {p:.1e} | {'YES' if p < 0.01 else 'no'} |")

    # sizing tables: single features and 2-feature combos
    def sizing(kind):
        idx = 1 if kind == "pickup" else 2  # denominator column: dials or connected
        print(f"\n### {kind} sizing (denominator = {'dials' if kind=='pickup' else 'connected calls'}/day)\n")
        print("| workflow | cohort | denom/day | base rate | n/arm 3pp | days 3pp | n/arm 5pp | days 5pp | n/arm 10pp | days 10pp | verdict |")
        print("|---|---|---|---|---|---|---|---|---|---|---|")
        rows = []
        combos = [("ALL", lambda c: (c[0], "all"))]
        for d in FEATS:
            combos.append((d, lambda c, d=d: (c[0], lead_feat.get(c[1], {}).get(d))))
        for d1 in range(len(FEATS)):
            for d2 in range(d1 + 1, len(FEATS)):
                a, b = FEATS[d1], FEATS[d2]
                combos.append((f"{a}x{b}", lambda c, a=a, b=b:
                               (c[0], f"{lead_feat.get(c[1],{}).get(a)}|{lead_feat.get(c[1],{}).get(b)}")))
        for name, keyfn in combos:
            out = agg(keyfn)
            for (wf, val), (dl, cn, e) in sorted(out.items()):
                nd = stats[wf]["nd"]
                denom_day = (dl if kind == "pickup" else cn) / nd
                base = (cn / dl) if kind == "pickup" else (e / cn if cn else 0)
                cells, worst_days = [], 0
                for delta in (0.03, 0.05, 0.10):
                    n = n_per_arm(base, delta)
                    # 2 arms share the cohort's daily denominator
                    dys = n / (denom_day / 2) if denom_day else float("inf")
                    cells += [n, dys]
                    if delta == 0.05:
                        worst_days = dys
                verdict = "OK" if worst_days <= 4 else ("slow" if worst_days <= 8 else "TOO SMALL")
                rows.append((wf, f"{name}={val}", denom_day, base, cells, verdict))
        for wf, coh, dd, base, cells, verdict in rows:
            c = [f"{cells[0]}", f"{cells[1]:.1f}", f"{cells[2]}", f"{cells[3]:.1f}", f"{cells[4]}", f"{cells[5]:.1f}"]
            print(f"| {wf} | {coh} | {dd:.0f} | {base:.3f} | {' | '.join(c)} | {verdict} |")

    print("\n## 6. Experiment sizing (two-proportion, alpha=0.05, power=0.80, 50/50 split)\n")
    sizing("engagement")
    sizing("pickup")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "scratch/history.ndjson")
