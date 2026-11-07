"""Step-6 incident analysis: baselines from this scenario's history, daily tables,
step-fit onset estimates, and rolling-window z-score detector simulation.

Usage: python scratch/analyze_probe03.py scratch/probe03
"""
import json
import math
import sys
from collections import defaultdict

prefix = sys.argv[1] if len(sys.argv) > 1 else "scratch/probe03"


def load(path):
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line:
            yield json.loads(line)


def rates(calls):
    """calls: list of (connected, engaged, halluc, adher) -> dict of rates."""
    n = len(calls)
    conn = [c for c in calls if c[0]]
    return dict(
        dials=n, connected=len(conn),
        pickup=len(conn) / n if n else 0,
        engagement=(sum(c[1] for c in conn) / len(conn)) if conn else 0,
        halluc=(sum(c[2] for c in conn) / len(conn)) if conn else 0,
        adher=(sum(c[3] for c in conn) / len(conn)) if conn else 0,
    )


def parse_calls(path):
    """-> per wf: list of (minute_of_stream, day, hour, caller_id, connected, engaged, halluc, adher); plus config events"""
    out = defaultdict(list)
    cfg_events = []
    for ev in load(path):
        if ev["type"] == "call":
            q = ev.get("qa") or {}
            out[ev["workflow_id"]].append((
                ev["ts"], ev["ts"][:10], int(ev["ts"][11:13]), ev["variant"]["caller_id"],
                ev["connected"], bool(ev.get("engaged")) if ev["connected"] else False,
                bool(q.get("hallucination_flag")) if ev["connected"] else False,
                q.get("flow_adherence") if ev["connected"] else None))
        elif ev["type"] not in ("lead", "campaign_created"):
            cfg_events.append(ev)
    return out, cfg_events


def tup(c):
    return (c[4], c[5], c[6], c[7] or 0)


hist, hist_cfg = parse_calls(f"{prefix}_history.ndjson")
live, live_cfg = parse_calls(f"{prefix}_live.ndjson")

print("## Baselines from THIS scenario's history\n")
print("| workflow | dials | pickup | engagement | halluc rate | flow_adherence | day-to-day sd (pickup/eng/halluc/adher) |")
print("|---|---|---|---|---|---|---|")
base = {}
for wf in sorted(hist):
    r = rates([tup(c) for c in hist[wf]])
    bydays = defaultdict(list)
    for c in hist[wf]:
        bydays[c[1]].append(tup(c))
    daily = [rates(v) for v in bydays.values()]
    sds = {k: math.sqrt(sum((d[k] - sum(x[k] for x in daily) / len(daily)) ** 2 for d in daily) / (len(daily) - 1))
           for k in ("pickup", "engagement", "halluc", "adher")}
    base[wf] = r
    base[wf]["sd"] = sds
    print(f"| {wf} | {r['dials']} | {r['pickup']:.3f} | {r['engagement']:.3f} | {r['halluc']:.4f} | {r['adher']:.3f} | "
          f"{sds['pickup']:.3f}/{sds['engagement']:.3f}/{sds['halluc']:.4f}/{sds['adher']:.3f} |")

print("\n### history pickup per caller_id\n")
print("| workflow | caller_id | dials | pickup |")
print("|---|---|---|---|")
base_cid = {}
for wf in sorted(hist):
    bycid = defaultdict(list)
    for c in hist[wf]:
        bycid[c[3]].append(tup(c))
    for cid, v in sorted(bycid.items()):
        r = rates(v)
        base_cid[(wf, cid)] = r
        print(f"| {wf} | {cid} | {r['dials']} | {r['pickup']:.3f} |")

print("\n## Config events in live stream (supervisor etc.)\n")
for ev in live_cfg:
    print("-", json.dumps(ev)[:300])

print("\n## Live run: per workflow per day\n")
print("| workflow | day | dials | pickup | engagement | halluc | adher | pickup by caller_id |")
print("|---|---|---|---|---|---|---|---|")
for wf in sorted(live):
    bydays = defaultdict(list)
    for c in live[wf]:
        bydays[c[1]].append(c)
    for day, v in sorted(bydays.items()):
        r = rates([tup(c) for c in v])
        bycid = defaultdict(list)
        for c in v:
            bycid[c[3]].append(tup(c))
        cids = " ".join(f"{cid}:{rates(x)['pickup']:.2f}" for cid, x in sorted(bycid.items()))
        print(f"| {wf} | {day} | {r['dials']} | {r['pickup']:.3f} | {r['engagement']:.3f} | "
              f"{r['halluc']:.4f} | {r['adher']:.3f} | {cids} |")


# ---- step-fit onset estimation on hourly series ----
def hourly_series(calls, metric):
    """metric: fn(call)->(num, den) aggregated per absolute hour key."""
    agg = defaultdict(lambda: [0, 0])
    for c in calls:
        num, den = metric(c)
        k = c[0][:13]  # YYYY-MM-DDTHH
        agg[k][0] += num
        agg[k][1] += den
    return sorted(agg.items())


def step_fit(series):
    """Fit a single step: return (onset_idx, before_rate, after_rate) minimising sq error."""
    xs = [(n / d if d else 0, d) for _, (n, d) in series]
    best = (None, 0, 0, float("inf"))
    tot_n = sum(n for _, (n, d) in series)
    tot_d = sum(d for _, (n, d) in series)
    cn = cd = 0
    for i in range(1, len(series)):
        cn += series[i - 1][1][0]
        cd += series[i - 1][1][1]
        if cd == 0 or tot_d - cd == 0:
            continue
        p1, p2 = cn / cd, (tot_n - cn) / (tot_d - cd)
        err = -(cn * math.log(max(p1, 1e-9)) + (cd - cn) * math.log(max(1 - p1, 1e-9))
                + (tot_n - cn) * math.log(max(p2, 1e-9))
                + ((tot_d - cd) - (tot_n - cn)) * math.log(max(1 - p2, 1e-9)))
        if err < best[3]:
            best = (i, p1, p2, err)
    i, p1, p2, _ = best
    return series[i][0], p1, p2


METRICS = {
    "pickup": lambda c: (1 if c[4] else 0, 1),
    "engagement": lambda c: ((1 if c[5] else 0, 1) if c[4] else (0, 0)),
    "halluc": lambda c: ((1 if c[6] else 0, 1) if c[4] else (0, 0)),
    "adher<0.8": lambda c: ((1 if (c[7] or 1) < 0.8 else 0, 1) if c[4] else (0, 0)),
}

print("\n## Step-fit (max-likelihood single changepoint) per workflow x metric, live stream\n")
print("| workflow | metric | onset (hour) | before | after | shift |")
print("|---|---|---|---|---|---|")
for wf in sorted(live):
    for m, fn in METRICS.items():
        s = hourly_series(live[wf], fn)
        if len(s) < 10:
            continue
        onset, p1, p2 = step_fit(s)
        print(f"| {wf} | {m} | {onset} | {p1:.3f} | {p2:.3f} | {p2-p1:+.3f} |")
    # per caller_id pickup
    cids = sorted({c[3] for c in live[wf]})
    for cid in cids:
        s = hourly_series([c for c in live[wf] if c[3] == cid], METRICS["pickup"])
        if len(s) < 10:
            continue
        onset, p1, p2 = step_fit(s)
        print(f"| {wf} | pickup[{cid}] | {onset} | {p1:.3f} | {p2:.3f} | {p2-p1:+.3f} |")


# ---- rolling-window z-score detector simulation ----
def simulate(wf, calls, metric_name, fn, baseline_p, windows=(60, 240, 1440), zthr=3.0, cooldown=1440):
    """Slide over calls in ts order; window = last W minutes of calls. Alarm when |z|>=zthr.
    Returns per window: list of (alarm_ts, calls_seen_in_stream, z, rate)."""
    import bisect
    seq = []
    for c in sorted(calls, key=lambda c: c[0]):
        num, den = fn(c)
        if den:
            seq.append((c[0], num))
    ts_min = []  # minutes since start
    t0 = None

    def mins(ts):
        d = (int(ts[8:10]), int(ts[11:13]), int(ts[14:16]))
        return d[0] * 1440 + d[1] * 60 + d[2] + (43200 if ts[5:7] != seq[0][0][5:7] else 0)

    vals = []
    for ts, v in seq:
        ts_min.append(mins(ts))
        vals.append(v)
    cum = [0]
    for v in vals:
        cum.append(cum[-1] + v)
    results = {}
    for W in windows:
        alarms = []
        last_alarm = -10**9
        for i in range(len(vals)):
            lo = bisect.bisect_left(ts_min, ts_min[i] - W)
            n = i - lo + 1
            if n < 30:
                continue
            x = cum[i + 1] - cum[lo]
            p = x / n
            se = math.sqrt(baseline_p * (1 - baseline_p) / n)
            if se == 0:
                continue
            z = (p - baseline_p) / se
            if abs(z) >= zthr and ts_min[i] - last_alarm >= cooldown:
                alarms.append((seq[i][0], i + 1, round(z, 1), round(p, 3)))
                last_alarm = ts_min[i]
        results[W] = alarms
    return results


print("\n## Detector simulation: rolling windows (1h/4h/24h), z vs history baseline, |z|>=3, 24h cooldown\n")
for wf in sorted(live):
    specs = [("pickup", METRICS["pickup"], base[wf]["pickup"]),
             ("engagement", METRICS["engagement"], base[wf]["engagement"]),
             ("halluc", METRICS["halluc"], base[wf]["halluc"])]
    for cid in sorted({c[3] for c in live[wf]}):
        bp = base_cid.get((wf, cid), {}).get("pickup")
        if bp:
            specs.append((f"pickup[{cid}]", METRICS["pickup"], bp))
    for name, fn, bp in specs:
        calls = live[wf] if "[" not in name else [c for c in live[wf] if c[3] == name.split("[")[1][:-1]]
        res = simulate(wf, calls, name, fn, bp)
        for W, alarms in res.items():
            if alarms:
                a = "; ".join(f"{t} (n={n}, z={z}, p={p})" for t, n, z, p in alarms[:6])
                print(f"- {wf} {name} W={W//60}h: {a}")
