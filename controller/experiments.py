"""Experiment engine (C6/C7) — design.md "Experiments and winners".

One experiment per workflow, one dimension at a time. Champion keeps 70%, up to two
challengers split 30%. Winner = deterministic two-proportion z-test at alpha=0.05
Bonferroni-corrected across challengers, judged only after min-n per arm (sized for a
10pp lift first). Guardrail KPI is checked before promotion. Promotion keeps 20% on the
old champion: that residual feeds the decay watch, which rolls back through governance.

Unit of analysis (D013): calls — dials for pickup, connected calls for engagement — not
persons. The simulator re-samples the variant on every dial, so arm assignment is not
clustered by person; repeated attempts and returning persons add mild positive correlation
WITHIN arms, which inflates variance slightly. We accept this (documented, not hidden) and
buffer it with min-n floors and the Bonferroni correction.

Option names, KPIs, guardrails, TTLs and routes all come from the policy API at runtime.
"""
import json
import logging
import math
from datetime import datetime, timedelta
from statistics import NormalDist

from . import govern
from . import policy as pol

log = logging.getLogger("experiments")

DIM_COL = {"welcome_message": "welcome", "voice": "voice", "caller_id": "caller_id"}
CHAMPION_SHARE, PROMOTE_SHARE = 0.7, 0.8
ALPHA = 0.05
LOOKS = 2  # sequential looks: at min-n(10pp) and min-n(5pp); alpha split across looks (D015)
MIN_N_FLOOR = 200
ACTIVE = ("split_proposed", "running", "promote_proposed", "promoted", "rollback_proposed")


# ---------- statistics (deterministic; no LLM anywhere near this) ----------

def n_per_arm(p1: float, delta: float, alpha: float, power: float = 0.8) -> int:
    nd = NormalDist()
    za, zb = nd.inv_cdf(1 - alpha / 2), nd.inv_cdf(power)
    p2 = min(max(p1 + delta, 1e-4), 1 - 1e-4)
    pbar = (p1 + p2) / 2
    num = (za * math.sqrt(2 * pbar * (1 - pbar)) + zb * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2
    return max(MIN_N_FLOOR, math.ceil(num / delta**2))


def ztest(x1: int, n1: int, x2: int, n2: int) -> tuple[float, float]:
    """(effect p1-p2, two-sided p-value)."""
    if not n1 or not n2:
        return 0.0, 1.0
    p1, p2 = x1 / n1, x2 / n2
    p = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0:
        return p1 - p2, 1.0
    z = (p1 - p2) / se
    return p1 - p2, math.erfc(abs(z) / math.sqrt(2))


def winner_test(arms: dict[str, tuple[int, int]], champion: str,
                alpha: float = ALPHA) -> dict | None:
    """arms: option -> (successes, trials). Returns winner verdict dict or None.
    Deterministic Bonferroni: each challenger tested at alpha/k, two-sided."""
    k = len(arms) - 1
    if k < 1:
        return None
    cx, cn = arms[champion]
    best = None
    for name, (x, n) in arms.items():
        if name == champion or not n:
            continue
        eff, p = ztest(x, n, cx, cn)
        if eff > 0 and p < alpha / k and (best is None or x / n > best["rate"]):
            best = {"winner": name, "rate": x / n, "champion_rate": cx / cn if cn else 0,
                    "effect": eff, "p": p, "alpha_used": alpha / k, "n": n, "champion_n": cn}
    return best


# ---------- helpers ----------

def kpi_parts(objective: dict) -> tuple[str, str, float]:
    """(primary_metric, guardrail_metric, guardrail_max_drop) from the runtime objective."""
    primary = objective.get("primary", "engagement_rate").replace("_rate", "")
    g = objective.get("guardrail", {})
    gm, gd = "pickup", 0.02
    for key, v in g.items():
        gm, gd = key.replace("_rate_max_drop", "").replace("_max_drop", ""), v
    return primary, gm, gd


def metric_nd(metric: str, dials: int, conn: int, eng: int) -> tuple[int, int]:
    return (conn, dials) if metric == "pickup" else (eng, conn)


def tv_distance(a: dict, b: dict) -> float:
    keys = set(a) | set(b)
    return 0.5 * sum(abs(a.get(k, 0) - b.get(k, 0)) for k in keys)


def arm_counts(store, wid: str, versions: list[int], dim: str) -> dict[str, tuple[int, int, int]]:
    col = DIM_COL[dim]
    qmarks = ",".join("?" * len(versions))
    rows = store.db.execute(
        f"SELECT {col}, SUM(dials), SUM(connected), SUM(engaged) FROM agg_calls "
        f"WHERE wid=? AND config_version IN ({qmarks}) GROUP BY {col}",
        [wid] + versions).fetchall()
    return {r[0]: (r[1], r[2], r[3]) for r in rows}


def dim_for(policy_w: dict, store, wid: str) -> str | None:
    """Next untested dimension for this workflow, driven by its primary KPI."""
    primary, _, _ = kpi_parts(policy_w.get("objective", {}))
    candidates = ["caller_id"] if primary == "pickup" else ["voice", "welcome_message"]
    done = {r[0] for r in store.db.execute(
        "SELECT dimension FROM experiments WHERE wid=?", (wid,)).fetchall()}
    for d in candidates:
        if d not in done and len(policy_w.get("options", {}).get(d, [])) >= 2:
            return d
    return None


def current_alloc(api, wid: str, dim: str) -> tuple[dict, dict, int]:
    cur = api.get_config(wid)
    cfg = cur["config"]
    alloc = dict(cfg["allocations"].get("default", {}).get(dim, {}))
    if not alloc:
        opts = None  # cohort omits dim -> effectively first option? default covers it
    return cfg, alloc, cur["version"]


def recent_option_rates(store, wid: str, dim: str, now: str, days: int = 7) -> dict:
    col = DIM_COL[dim]
    since = (datetime.fromisoformat(now) - timedelta(days=days)).isoformat()[:13]
    rows = store.db.execute(
        f"SELECT {col}, SUM(dials), SUM(connected), SUM(engaged) FROM agg_calls "
        f"WHERE wid=? AND hour_ts>=? GROUP BY {col}", (wid, since)).fetchall()
    return {r[0]: {"dials": r[1], "connected": r[2], "engaged": r[3],
                   "pickup": round(r[2] / r[1], 4) if r[1] else None,
                   "engagement": round(r[3] / r[2], 4) if r[2] else None} for r in rows}


def _gates_ok(api, store, policy_w, wid, now, state, need_days: float = 0) -> bool:
    if pol.request_budget_left(store, policy_w, wid, now) <= 0:
        return False
    nowdt = datetime.fromisoformat(now)
    if pol.good_send_time(policy_w, nowdt) is not None:
        return False
    pref_h = pol.preferences(wid).get("earliest_proposal_hour")
    if pref_h is not None and nowdt.hour < pref_h:
        return False
    end_minute = int(store.get_meta("end_minute", 0))  # advance responses don't carry it
    if need_days and (end_minute - state["sim_minute"]) < need_days * 1440:
        return False
    pending = store.db.execute("SELECT COUNT(*) FROM proposals WHERE wid=? AND status IN "
                               "('pending','approved')", (wid,)).fetchone()[0]
    return pending == 0


def _queue_change(api, store, policy_w, wid, now, dim, new_alloc, old_alloc, base_cfg,
                  base_version, summary, rationale, impact, dry_run, attempt=1):
    cfg = json.loads(json.dumps(base_cfg))
    cfg.setdefault("allocations", {}).setdefault("default", {})[dim] = new_alloc
    diff = {f"allocations.default.{dim}": new_alloc}
    affected = store.db.execute("SELECT COUNT(*) FROM leads WHERE wid=? AND done=0",
                                (wid,)).fetchone()[0]
    route = pol.route(policy_w, {dim}, tv_distance(new_alloc, old_alloc))
    if route == "auto":
        payload = {"workflow_id": wid, "base_version": base_version, "proposed_config": cfg,
                   "rationale": rationale}
    else:
        payload = {"workflow_id": wid, "base_version": base_version, "proposed_config": cfg,
                   "change_summary": summary, "diff": diff, "affected_leads": affected,
                   "dry_run": dry_run, "impact_score": impact, "rationale": rationale,
                   "expires_in_hours": pol.expires_in_hours(policy_w)}
    return govern.queue_intent(store, now, wid, "approval" if route == "approval" else "auto",
                               base_version, payload, diff, attempt=attempt)


def _applied_version(store, wid: str, proposal_id: str) -> int | None:
    # the version arrives on the config_changed event carrying our proposal_id
    row = store.db.execute(
        "SELECT ref FROM audit WHERE wid=? AND kind='config_changed' AND "
        "json_extract(details,'$.proposal_id')=?", (wid, proposal_id)).fetchone()
    return int(row[0][1:]) if row else None  # ref is 'v<version>'


# ---------- engine ----------

def step(api, store, now: str, state: dict):
    for wid in pol.all_wids(store):
        policy_w = pol.get(store, wid)
        try:
            _step_wf(api, store, wid, policy_w, now, state)
        except Exception:
            log.exception("experiment step failed for %s", wid)


def _step_wf(api, store, wid: str, policy_w: dict, now: str, state: dict):
    primary, gmetric, gdrop = kpi_parts(policy_w.get("objective", {}))
    exp = store.db.execute(
        "SELECT exp_id, dimension, arms, start_version, status, notes FROM experiments "
        "WHERE wid=? AND status IN (%s)" % ",".join("?" * len(ACTIVE)),
        (wid, *ACTIVE)).fetchone()

    if exp:
        exp_id, dim, arms_j, start_version, status, notes_j = exp
        arms = json.loads(arms_j)
        notes = json.loads(notes_j or "{}")
        # supervisor edit while active -> invalid (D014); fresh restart next tick
        if start_version is not None and store.db.execute(
                "SELECT COUNT(*) FROM config_versions WHERE wid=? AND version>? AND actor='supervisor'",
                (wid, start_version)).fetchone()[0]:
            with store.db:
                store.db.execute("UPDATE experiments SET status='invalid', decided_ts=? WHERE exp_id=?",
                                 (now, exp_id))
                store.audit(now, wid, "experiment_invalid", exp_id, {"reason": "supervisor edit"})
            return
        if status in ("split_proposed", "promote_proposed", "rollback_proposed"):
            _track_proposal(api, store, wid, exp_id, status, notes, now)
        elif status == "running":
            _extend_versions(api, store, wid, exp_id, dim, notes, now)
            _judge(api, store, wid, policy_w, exp_id, dim, arms, notes, primary,
                   gmetric, gdrop, now, state)
        elif status == "promoted":
            _decay_watch(api, store, wid, policy_w, exp_id, dim, arms, notes, primary, now, state)
        return

    # no active experiment: start one if gates allow and enough scenario time remains
    dim = dim_for(policy_w, store, wid)
    if not dim or not _gates_ok(api, store, policy_w, wid, now, state, need_days=2):
        return
    cfg, alloc, version = current_alloc(api, wid, dim)
    options = policy_w["options"][dim]
    if not alloc:
        alloc = {options[0]: 1.0}
    champion = max(alloc, key=alloc.get)
    # ALL other options become challengers in ONE proposal: one approval starts the whole
    # test, and the Bonferroni alpha/k correction already covers the extra comparisons (D015).
    challengers = [o for o in options if o != champion]
    if not challengers:
        return
    share = 0.3 / len(challengers)  # 30% TOTAL challenger traffic, split evenly
    new_alloc = {champion: CHAMPION_SHARE, **{c: round(share, 3) for c in challengers}}
    rates = recent_option_rates(store, wid, dim, now)
    base_rate = (rates.get(champion, {}) or {}).get(primary) or 0.5
    min_n = n_per_arm(base_rate, 0.10, ALPHA / (len(challengers) * LOOKS))
    exp_id = f"exp_{wid}_{dim}_{len(store.db.execute('SELECT exp_id FROM experiments WHERE wid=?', (wid,)).fetchall())+1}"
    summary = (f"A/B test on {dim}: keep {champion} at {int(CHAMPION_SHARE*100)}%, "
               f"try {', '.join(challengers)} at {int(share*100)}% each")
    rationale = (f"Exploration of untested {dim} options on primary KPI {primary}. Winner will be "
                 f"decided by a two-proportion z-test (alpha {ALPHA}/{len(challengers)} Bonferroni) "
                 f"after at least {min_n} {('dials' if primary=='pickup' else 'connected calls')} per arm. "
                 f"Guardrail {gmetric} checked before any promotion.")
    dry_run = {"observed_option_rates_last7d": rates,
               "note": "history ran under a single variant; challenger rates unknown — "
                       "this is exploration, expected impact under the null is 0"}
    with store.db:
        pid = _queue_change(api, store, policy_w, wid, now, dim, new_alloc, alloc, cfg, version,
                            summary, rationale, round(0.3 * 0.1, 3), dry_run)
        store.db.execute(
            "INSERT INTO experiments(exp_id,wid,dimension,cohort,arms,start_version,status,"
            "started_ts,notes) VALUES(?,?,?,?,?,?,?,?,?)",
            (exp_id, wid, dim, "default", json.dumps({"champion": champion,
                                                      "challengers": challengers}),
             None, "split_proposed",
             now, json.dumps({"proposal_id": pid, "original_alloc": alloc, "min_n": min_n,
                              "split_alloc": new_alloc, "versions": []})))
        store.audit(now, wid, "experiment_started", exp_id,
                    {"dim": dim, "champion": champion, "challengers": challengers,
                     "min_n_per_arm": min_n, "proposal_id": pid})


def _track_proposal(api, store, wid, exp_id, status, notes, now):
    pid = notes.get("proposal_id")
    row = store.db.execute("SELECT status FROM proposals WHERE proposal_id=?", (pid,)).fetchone()
    pstatus = row[0] if row else None
    if pstatus == "applied" or (pstatus is None and store.db.execute(
            "SELECT status FROM intents WHERE proposal_id=?", (pid,)).fetchone() in (("acked",),)):
        ver = _applied_version(store, wid, pid)
        if ver is None:
            return  # config_changed event not ingested yet
        nxt = {"split_proposed": "running", "promote_proposed": "promoted",
               "rollback_proposed": "done"}[status]
        notes["versions"] = notes.get("versions", []) + [ver]
        notes["active_version"] = ver
        with store.db:
            store.db.execute("UPDATE experiments SET status=?, start_version=?, notes=? WHERE exp_id=?",
                             (nxt, notes["versions"][0] if nxt == "running" else ver,
                              json.dumps(notes), exp_id))
            store.audit(now, wid, f"experiment_{nxt}", exp_id, {"version": ver})
    elif pstatus in ("rejected", "expired", "lapsed", "stale"):
        attempt = notes.get("attempt", 1)
        if pstatus == "rejected" and attempt < 2 and not notes.get("retried"):
            notes["retried"] = True  # one retry with a fresh attempt id (D010), next tick's gates
            with store.db:
                store.db.execute("UPDATE experiments SET status='failed', notes=? WHERE exp_id=?",
                                 (json.dumps(notes), exp_id))
                store.audit(now, wid, "experiment_failed", exp_id,
                            {"proposal_status": pstatus, "will_retry": True})
        else:
            with store.db:
                store.db.execute("UPDATE experiments SET status='failed', notes=? WHERE exp_id=?",
                                 (json.dumps(notes), exp_id))
                store.audit(now, wid, "experiment_failed", exp_id, {"proposal_status": pstatus})


def _extend_versions(api, store, wid, exp_id, dim, notes, now):
    """A non-supervisor config change on ANOTHER dim (e.g. our caller_id remediation) bumps
    the version; if the new version preserves this experiment's split, keep counting under it
    — otherwise the experiment's data would silently stall at the old version."""
    versions = notes.get("versions", [])
    if not versions:
        return
    latest = store.db.execute("SELECT MAX(version) FROM config_versions WHERE wid=?",
                              (wid,)).fetchone()[0]
    if latest is None or latest <= max(versions):
        return
    cfg, alloc, version = current_alloc(api, wid, dim)
    split = notes.get("split_alloc", {})
    if version > max(versions) and all(abs(alloc.get(o, 0) - w) < 1e-6 for o, w in split.items()):
        notes["versions"] = versions + list(range(max(versions) + 1, version + 1))
        with store.db:
            store.db.execute("UPDATE experiments SET notes=? WHERE exp_id=?",
                             (json.dumps(notes), exp_id))
            store.audit(now, wid, "experiment_versions_extended", exp_id,
                        {"to_version": version})


def _judge(api, store, wid, policy_w, exp_id, dim, arms, notes, primary, gmetric, gdrop,
           now, state):
    versions = notes.get("versions") or [notes.get("active_version")]
    counts = arm_counts(store, wid, versions, dim)
    champion, challengers = arms["champion"], arms["challengers"]
    prim = {o: metric_nd(primary, *counts.get(o, (0, 0, 0))) for o in [champion] + challengers}
    cx, cn = prim[champion]
    base = cx / cn if cn else 0.5
    k = len(challengers)
    # Two fixed looks (D015): at min-n for 10pp and at min-n for 5pp. Testing at every tick
    # would inflate false winners (measured 8-12% in the sequential A/A); fixed looks with
    # alpha split across looks keep it under the 5% family bound (measured ~2%).
    look = notes.get("look", 0)
    threshold = notes.get("min_n", MIN_N_FLOOR) if look == 0 else \
        n_per_arm(base, 0.05, ALPHA / (k * LOOKS))
    if any(prim[o][1] < threshold for o in prim):
        return  # not enough evidence for this look yet
    verdict = winner_test(prim, champion, alpha=ALPHA / LOOKS)
    if verdict:
        g = {o: metric_nd(gmetric, *counts.get(o, (0, 0, 0))) for o in (champion, verdict["winner"])}
        geff, gp = ztest(*g[verdict["winner"]], *g[champion])
        guard_ok = (geff > -gdrop) and not (geff < 0 and gp < 0.05)
        if not guard_ok:
            with store.db:
                store.db.execute("UPDATE experiments SET status='done', decided_ts=?, winner=NULL,"
                                 " notes=? WHERE exp_id=?",
                                 (now, json.dumps(notes | {"guardrail_blocked": verdict}), exp_id))
                store.audit(now, wid, "experiment_guardrail_block", exp_id,
                            {"verdict": verdict, "guardrail_effect": geff, "p": gp,
                             "max_drop": gdrop})
            _revert(api, store, policy_w, wid, dim, notes, now, "guardrail block")
            return
        if _gates_ok(api, store, policy_w, wid, now, state):
            _promote(api, store, policy_w, wid, exp_id, dim, arms, notes, verdict,
                     primary, counts, now)
        return
    # no winner at this look: check for significant harm; else advance to the next look
    harm = None
    for c in challengers:
        x, n = prim[c]
        eff, p = ztest(x, n, cx, cn)
        if eff < -0.03 and p < ALPHA / (LOOKS * k):
            harm = {"challenger": c, "effect": eff, "p": p}
            break
    if not harm and look == 0:
        notes["look"] = 1
        with store.db:
            store.db.execute("UPDATE experiments SET notes=? WHERE exp_id=?",
                             (json.dumps(notes), exp_id))
            store.audit(now, wid, "experiment_look_passed", exp_id,
                        {"look": 1, "counts": {o: list(prim[o]) for o in prim}})
        return
    exhausted = look >= LOOKS - 1
    if harm or exhausted:
        if _gates_ok(api, store, policy_w, wid, now, state):
            with store.db:
                store.db.execute("UPDATE experiments SET status='done', decided_ts=?, notes=? "
                                 "WHERE exp_id=?",
                                 (now, json.dumps(notes | {"end_reason": harm or "no winner at 5pp",
                                                           "final_counts": {k: list(v) for k, v in prim.items()}}),
                                  exp_id))
                store.audit(now, wid, "experiment_ended", exp_id,
                            {"harm": harm, "exhausted": exhausted})
            _revert(api, store, policy_w, wid, dim, notes, now,
                    "challenger significantly harmful" if harm else "no winner at 5pp sensitivity")


def _promote(api, store, policy_w, wid, exp_id, dim, arms, notes, verdict, primary, counts, now):
    winner, champion = verdict["winner"], arms["champion"]
    new_alloc = {winner: PROMOTE_SHARE, champion: round(1 - PROMOTE_SHARE, 3)}
    cfg, alloc, version = current_alloc(api, wid, dim)
    daily = store.db.execute(
        "SELECT SUM(dials), SUM(connected), SUM(engaged) FROM agg_calls WHERE wid=? AND hour_ts>=?",
        (wid, (datetime.fromisoformat(now) - timedelta(days=1)).isoformat()[:13])).fetchone()
    daily_primary = (daily[1] if primary == "pickup" else daily[2]) or 1
    share_moved = PROMOTE_SHARE - notes.get("split_alloc", {}).get(winner, 0.15)
    vol = (daily[0] if primary == "pickup" else daily[1]) or 0
    impact = max(0.0, min(1.0, verdict["effect"] * share_moved * vol / daily_primary))
    summary = (f"Promote {dim}={winner}: measured {verdict['effect']*100:+.1f}pp {primary} vs "
               f"{champion} (n={verdict['n']}/{verdict['champion_n']}, p={verdict['p']:.4f})")
    rationale = (f"Experiment {exp_id}: {winner} {primary}={verdict['rate']:.3f} vs champion "
                 f"{verdict['champion_rate']:.3f} at alpha={verdict['alpha_used']:.4f} "
                 f"(Bonferroni). Guardrail respected. Winner keeps {int(PROMOTE_SHARE*100)}%; "
                 f"{int((1-PROMOTE_SHARE)*100)}% stays on {champion} for decay monitoring.")
    dry_run = {"arm_counts": {k: list(v) for k, v in counts.items()},
               "expected_extra_per_day": round(verdict["effect"] * share_moved * vol, 1),
               "window_versions": notes.get("versions")}
    with store.db:
        pid = _queue_change(api, store, policy_w, wid, now, dim, new_alloc, alloc, cfg, version,
                            summary, rationale, round(impact, 3), dry_run)
        notes["proposal_id"] = pid
        notes["promoted_winner"] = winner
        store.db.execute("UPDATE experiments SET status='promote_proposed', winner=?, notes=? "
                         "WHERE exp_id=?", (winner, json.dumps(notes), exp_id))
        store.audit(now, wid, "experiment_promote_proposed", exp_id, {"verdict": verdict,
                                                                      "impact_score": impact})


def _decay_watch(api, store, wid, policy_w, exp_id, dim, arms, notes, primary, now, state):
    winner = notes.get("promoted_winner")
    residual = arms["champion"]
    ver = notes.get("active_version")
    since = (datetime.fromisoformat(now) - timedelta(hours=48)).isoformat()[:13]
    col = DIM_COL[dim]
    rows = store.db.execute(
        f"SELECT {col}, SUM(dials), SUM(connected), SUM(engaged) FROM agg_calls "
        f"WHERE wid=? AND config_version>=? AND hour_ts>=? GROUP BY {col}",
        (wid, ver, since)).fetchall()
    c = {r[0]: (r[1], r[2], r[3]) for r in rows}
    wnd = metric_nd(primary, *c.get(winner, (0, 0, 0)))
    rnd = metric_nd(primary, *c.get(residual, (0, 0, 0)))
    if wnd[1] < MIN_N_FLOOR or rnd[1] < 100:
        return
    eff, p = ztest(*wnd, *rnd)
    if eff < -0.03 and p < 0.05 and _gates_ok(api, store, policy_w, wid, now, state):
        cfg, alloc, version = current_alloc(api, wid, dim)
        new_alloc = {residual: PROMOTE_SHARE, winner: round(1 - PROMOTE_SHARE, 3)}
        summary = f"Roll back {dim}={winner}: decayed, now {eff*100:+.1f}pp {primary} vs {residual}"
        rationale = (f"Decay watch on {exp_id}: over the last 48h {winner} {primary} is "
                     f"significantly below the residual champion {residual} "
                     f"(effect {eff*100:+.1f}pp, p={p:.4f}, n={wnd[1]}/{rnd[1]}). Restoring "
                     f"{residual}.")
        dry_run = {"last48h_counts": {k: list(v) for k, v in c.items()}}
        with store.db:
            pid = _queue_change(api, store, policy_w, wid, now, dim, new_alloc, alloc, cfg,
                                version, summary, rationale, 0.2, dry_run)
            notes["proposal_id"] = pid
            store.db.execute("UPDATE experiments SET status='rollback_proposed', notes=? "
                             "WHERE exp_id=?", (json.dumps(notes), exp_id))
            store.audit(now, wid, "experiment_rollback_proposed", exp_id,
                        {"effect": eff, "p": p})


def _revert(api, store, policy_w, wid, dim, notes, now, reason):
    orig = notes.get("original_alloc")
    if not orig:
        return
    cfg, alloc, version = current_alloc(api, wid, dim)
    if alloc == orig:
        return
    summary = f"End experiment on {dim}: restore previous allocation ({reason})"
    rationale = f"Experiment ended: {reason}. Restoring the pre-experiment allocation {orig}."
    with store.db:
        _queue_change(api, store, policy_w, wid, now, dim, orig, alloc, cfg, version,
                      summary, rationale, 0.05, {"restores": orig, "reason": reason}, attempt=2)
