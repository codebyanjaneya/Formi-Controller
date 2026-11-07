"""Detection + remediation (design.md section 6, rules generic / baseline-relative only).

Signals, in priority order:
1. External config_changed (actor != ours): hard signal. Stats are version-segmented
   already; pending proposals go stale; running experiments are invalidated (experiments.py);
   a before/after KPI comparison is audited; a bad external PROMPT change shows up via (2).
2. Sliced rolling-window z-detector vs hour-matched history baselines, on a LIMITED fixed
   slice list: workflow aggregate (pickup/engagement/halluc) + pickup per caller_id option.
   Alarm needs ALL of: |z| >= 3, |effect| >= 3pp, n >= 300 (and >= 5 positives for rare
   metrics), PERSISTENCE over 2 consecutive ticks, and a 24h cooldown per series. The
   limited list + persistence + cooldown are the multiple-comparisons control (D004).
3. 24h slow-drift backstop with the same effect-size floor.

Remediation:
- degraded caller_id: shift its weight to the healthiest other option; auto-apply where the
  policy allows (staged in max_shift steps), approval otherwise.
- hallucination spike: suggest-fixes -> validation (n>=200) -> prompt proposal with evidence
  -> post-apply verification; previous known-good prompt is always candidate #1.
"""
import json
import logging
import math
from datetime import datetime, timedelta

from .api import ApiError
from . import govern
from . import policy as pol

log = logging.getLogger("detect")

from .tuning import (Z_THR, EFFECT_FLOOR, MIN_N, MIN_POS, PERSIST, COOLDOWN_H, WINDOW_H,
                     DRIFT_WINDOW_H, VALIDATION_N, VERIFY_AFTER_H, RECALIB_H, RECALIB_CLAMP,
                     ROTATE_SLICE_MARGIN, ROTATE_MAX_SLICE_SHARE, ROTATE_HEALTHY_MIN_DIALS,
                     MAX_AUTO_PER_DAY, CREDIT_RESERVE_FRAC)


# ---------- series ----------

def _window_counts(store, wid, since_hour, caller_id=None):
    q = ("SELECT CAST(substr(hour_ts,12,2) AS INT) h, SUM(dials), SUM(connected), SUM(engaged),"
         " SUM(halluc) FROM agg_calls WHERE wid=? AND hour_ts>=?")
    args = [wid, since_hour]
    if caller_id:
        q += " AND caller_id=?"
        args.append(caller_id)
    return store.db.execute(q + " GROUP BY h", args).fetchall()


def _baseline(store, wid, metric, slice_, hour):
    row = store.db.execute("SELECT rate, n FROM baselines WHERE wid=? AND metric=? AND slice=?"
                           " AND hour=?", (wid, metric, slice_, hour)).fetchone()
    return row


def _scale(store, wid, metric, slice_):
    row = store.db.execute("SELECT factor FROM baseline_scale WHERE wid=? AND metric=? AND "
                           "slice=?", (wid, metric, slice_)).fetchone()
    return row[0] if row else 1.0


def recalibrate(store, now: str, nowdt):
    """Daily level recalibration (design 6.7): history gives the hourly SHAPE, but its LEVEL
    can sit a few pp off the live world (seen on both public scenarios). Scale each series'
    baseline by observed/expected over the last 72h, clamped to [0.85, 1.15], skipping series
    with an open incident so real degradations are never absorbed into the baseline."""
    since = (nowdt - timedelta(hours=RECALIB_H)).isoformat()[:13]
    for wid in pol.all_wids(store):
        policy_w = pol.get(store, wid)
        for metric, slice_, cid in _series_list(store, wid, policy_w):
            open_inc = store.db.execute(
                "SELECT 1 FROM incidents WHERE wid=? AND metric=? AND slice=? AND "
                "resolved_ts IS NULL", (wid, metric, slice_)).fetchone()
            if open_inc:
                continue
            x = n = exp = 0.0
            for h, dials, conn, eng, hal in _window_counts(store, wid, since, cid):
                den = dials if metric == "pickup" else conn
                num = {"pickup": conn, "engagement": eng, "halluc": hal}[metric]
                b = _baseline(store, wid, metric, slice_, h)
                if not b or not den:
                    continue
                x += num
                n += den
                exp += b[0] * den
            if n < 2 * MIN_N or exp <= 0:
                continue
            factor = max(RECALIB_CLAMP[0], min(RECALIB_CLAMP[1], x / exp))
            store.db.execute("INSERT OR REPLACE INTO baseline_scale(wid,metric,slice,factor,"
                             "updated_ts) VALUES(?,?,?,?,?)", (wid, metric, slice_, factor, now))
    store.db.commit()


def _zscore(store, wid, metric, slice_, rows):
    """Hour-matched z: expected successes under baseline vs observed, over the window rows."""
    x = n = exp = var = 0.0
    scale = _scale(store, wid, metric, slice_)
    for h, dials, conn, eng, hal in rows:
        den = dials if metric == "pickup" else conn
        num = {"pickup": conn, "engagement": eng, "halluc": hal}[metric]
        b = _baseline(store, wid, metric, slice_, h)
        if not b or not den:
            continue
        rate = min(0.999, max(0.001, b[0] * scale))
        x += num
        n += den
        exp += rate * den
        var += rate * (1 - rate) * den
    if n < MIN_N or var <= 0:
        return None
    if metric == "halluc" and x < MIN_POS:
        return None
    z = (x - exp) / math.sqrt(var)
    return {"z": z, "effect": x / n - exp / n, "n": int(n), "observed": x / n,
            "expected": exp / n}


def _series_list(store, wid, policy_w):
    out = [("pickup", "all", None), ("engagement", "all", None), ("halluc", "all", None)]
    for cid in policy_w.get("options", {}).get("caller_id", []):
        out.append(("pickup", f"caller_id={cid}", cid))
    return out


# ---------- main step ----------

def step(api, store, now: str, state: dict):
    _handle_externals(api, store, now)
    nowdt = datetime.fromisoformat(now)
    day = now[:10]
    if store.get_meta("recalib_day") != day:
        recalibrate(store, now, nowdt)
        store.set_meta("recalib_day", day)
        store.db.commit()
    for wid in pol.all_wids(store):
        policy_w = pol.get(store, wid)
        try:
            _scan_workflow(api, store, wid, policy_w, now, nowdt, state)
            _verify_open_incidents(api, store, wid, policy_w, now, nowdt, state)
        except Exception:
            log.exception("detect failed for %s", wid)


def _scan_workflow(api, store, wid, policy_w, now, nowdt, state):
    for window_h, tag in ((WINDOW_H, "4h"), (DRIFT_WINDOW_H, "24h")):
        since = (nowdt - timedelta(hours=window_h)).isoformat()[:13]
        for metric, slice_, cid in _series_list(store, wid, policy_w):
            rows = _window_counts(store, wid, since, cid)
            r = _zscore(store, wid, metric, slice_, rows)
            key = f"{wid}|{metric}|{slice_}|{tag}"
            if not r or abs(r["z"]) < Z_THR or abs(r["effect"]) < EFFECT_FLOOR \
                    or (metric != "halluc" and r["effect"] > 0) \
                    or (metric == "halluc" and r["effect"] < 0):
                store.db.execute("DELETE FROM detect_state WHERE key=?", (key,))
                continue
            row = store.db.execute("SELECT consec, last_alarm FROM detect_state WHERE key=?",
                                   (key,)).fetchone()
            consec = (row[0] if row else 0) + 1
            last_alarm = row[1] if row else None
            store.db.execute("INSERT OR REPLACE INTO detect_state(key,consec,last_alarm)"
                             " VALUES(?,?,?)", (key, consec, last_alarm))
            if consec < PERSIST:
                continue
            if last_alarm and (nowdt - datetime.fromisoformat(last_alarm)
                               ).total_seconds() < COOLDOWN_H * 3600:
                continue
            store.db.execute("UPDATE detect_state SET last_alarm=? WHERE key=?", (now, key))
            with store.db:
                cur = store.db.execute(
                    "INSERT INTO incidents(wid,slice,metric,onset_ts,detected_ts,action)"
                    " VALUES(?,?,?,?,?,?)",
                    (wid, slice_, metric, since, now,
                     json.dumps({"window": tag, **{k: round(v, 4) if isinstance(v, float) else v
                                                   for k, v in r.items()}})))
                store.audit(now, wid, "incident_detected", f"inc{cur.lastrowid}",
                            {"metric": metric, "slice": slice_, "window": tag,
                             "z": round(r["z"], 1), "effect": round(r["effect"], 4),
                             "n": r["n"]})
            log.info("INCIDENT %s %s %s z=%.1f effect=%+.3f n=%d (%s window)",
                     wid, metric, slice_, r["z"], r["effect"], r["n"], tag)
            _remediate(api, store, wid, policy_w, cur.lastrowid, metric, slice_, cid, r,
                       now, state)


def _handle_externals(api, store, now):
    cursor = int(store.get_meta("detect_audit_cursor", 0))
    rows = store.db.execute(
        "SELECT id, ts, wid, details FROM audit WHERE kind='config_changed' AND id>? ORDER BY id",
        (cursor,)).fetchall()
    last = cursor
    for aid, ts, wid, details in rows:
        last = aid
        d = json.loads(details)
        if d.get("actor") in ("controller_approved", "controller_auto"):
            continue
        log.info("external config change on %s by %s: %s", wid, d.get("actor"),
                 d.get("changed_dims"))
        with store.db:
            govern.mark_stale_on_external_change(store, wid, now)
            store.audit(now, wid, "external_change_handled", "",
                        {"actor": d.get("actor"), "changed_dims": d.get("changed_dims")})
    with store.db:
        store.set_meta("detect_audit_cursor", last)


# ---------- remediation ----------

def _remediate(api, store, wid, policy_w, incident_id, metric, slice_, cid, r, now, state):
    if metric == "pickup" and cid is not None and r["effect"] < 0:
        # rotate only when THIS caller_id is clearly worse than the workflow aggregate —
        # if everything is down equally, the caller id is not the cause
        nowdt = datetime.fromisoformat(now)
        since = (nowdt - timedelta(hours=WINDOW_H)).isoformat()[:13]
        r_all = _zscore(store, wid, "pickup", "all", _window_counts(store, wid, since))
        all_n = r_all["n"] if r_all else 0
        if r_all and r["effect"] - r_all["effect"] > -ROTATE_SLICE_MARGIN:
            store.audit(now, wid, "incident_no_action", f"inc{incident_id}",
                        {"reason": "slice not clearly worse than aggregate",
                         "slice_effect": r["effect"], "aggregate_effect": r_all["effect"]})
            return
        if all_n and r["n"] / all_n > ROTATE_MAX_SLICE_SHARE:
            store.audit(now, wid, "incident_no_action", f"inc{incident_id}",
                        {"reason": "slice carries nearly all traffic; rotating it cannot be "
                                   "justified against the aggregate", "share": r["n"] / all_n})
            return
        open_rot = store.db.execute(
            "SELECT 1 FROM incidents WHERE wid=? AND id!=? AND resolved_ts IS NULL AND "
            "json_extract(action,'$.kind')='rotate_caller_id'", (wid, incident_id)).fetchone()
        if open_rot:
            return  # one rotation at a time per workflow
        _rotate_caller_id(api, store, wid, policy_w, incident_id, cid, r, now)
    elif metric == "halluc":
        _prompt_pipeline(api, store, wid, policy_w, incident_id, r, now)
    # engagement-drop aggregate: if a recent external prompt change exists, the halluc
    # series usually fires too; otherwise we log it (no safe automatic lever).


def _rotate_caller_id(api, store, wid, policy_w, incident_id, bad_cid, r, now):
    cur = api.get_config(wid)
    cfg = json.loads(json.dumps(cur["config"]))
    alloc = dict(cfg["allocations"].get("default", {}).get("caller_id", {}))
    if not alloc:
        alloc = {o: 1 / len(policy_w["options"]["caller_id"])
                 for o in policy_w["options"]["caller_id"]}
    bad_w = alloc.get(bad_cid, 0)
    if bad_w <= 0.01:
        return  # already rotated away
    # auto-change safety brake: never more than 8 config changes/day from rotation
    day_autos = store.db.execute(
        "SELECT COUNT(*) FROM intents WHERE wid=? AND kind='auto' AND created_ts>=?",
        (wid, (datetime.fromisoformat(now) - timedelta(hours=24)).isoformat())).fetchone()[0]
    if day_autos >= MAX_AUTO_PER_DAY:
        store.audit(now, wid, "incident_no_action", f"inc{incident_id}",
                    {"reason": f"auto-apply rate limit reached ({MAX_AUTO_PER_DAY}/24h)"})
        return
    # target must be PROVEN healthy: enough recent traffic and clearly better pickup than
    # the degraded option — rotating onto an option with no data caused a ping-pong storm
    # in testing (never again).
    since = (datetime.fromisoformat(now) - timedelta(hours=24)).isoformat()[:13]
    rows = store.db.execute(
        "SELECT caller_id, SUM(dials), SUM(connected) FROM agg_calls WHERE wid=? AND hour_ts>=?"
        " GROUP BY caller_id", (wid, since)).fetchall()
    rates = {c: (co / d) for c, d, co in rows if c != bad_cid and d and d >= ROTATE_HEALTHY_MIN_DIALS}
    healthy = {c: rt for c, rt in rates.items() if rt >= r["observed"] + EFFECT_FLOOR}
    if not healthy:
        store.audit(now, wid, "incident_no_action", f"inc{incident_id}",
                    {"reason": "no proven-healthy alternative caller_id (need >=200 recent "
                               "dials and pickup >= degraded + 3pp)", "recent_rates": rates})
        return
    best = max(healthy, key=healthy.get)
    # spread the bad option's weight across ALL healthy options (equal parts): pushing
    # everything onto one number invites saturation of that number
    target = {k: v for k, v in alloc.items() if k != bad_cid}
    for h in healthy:
        target[h] = round(target.get(h, 0) + bad_w / len(healthy), 3)
    auto = policy_w.get("governance", {}).get("auto_apply", {})
    can_auto = (auto.get("enabled") and "caller_id" in auto.get("allowed_dims", []))
    max_shift = auto.get("max_shift", 0)
    summary = f"Rotate degraded caller_id {bad_cid} -> {best}"
    rationale = (f"Incident inc{incident_id}: pickup on {bad_cid} at {r['observed']:.3f} vs "
                 f"hour-matched baseline {r['expected']:.3f} (z={r['z']:.1f}, n={r['n']}). "
                 f"Moving its {bad_w:.0%} to {best} (best recent pickup).")
    with store.db:
        if can_auto and max_shift > 0:
            # staged: one max_shift step now; next tick's scan re-fires until weight is 0
            step_w = min(bad_w, max_shift)
            staged = dict(alloc)
            staged[bad_cid] = round(bad_w - step_w, 3)
            staged[best] = round(staged.get(best, 0) + step_w, 3)
            if staged[bad_cid] <= 0.011:
                staged.pop(bad_cid)
            payload = {"workflow_id": wid, "base_version": cur["version"],
                       "proposed_config": _with_alloc(cfg, "caller_id", staged),
                       "rationale": rationale}
            pid = govern.queue_intent(store, now, wid, "auto", cur["version"], payload,
                                      {"allocations.default.caller_id": staged},
                                      attempt=_next_attempt(store, wid, now))
        else:
            payload = {"workflow_id": wid, "base_version": cur["version"],
                       "proposed_config": _with_alloc(cfg, "caller_id", target),
                       "change_summary": summary,
                       "diff": {"allocations.default.caller_id": target},
                       "affected_leads": store.db.execute(
                           "SELECT COUNT(*) FROM leads WHERE wid=? AND done=0", (wid,)).fetchone()[0],
                       "dry_run": {"recent_pickup_by_caller_id": rates,
                                   "degraded": {bad_cid: r["observed"]},
                                   "baseline": r["expected"]},
                       "impact_score": min(1.0, abs(r["effect"]) * bad_w * 4),
                       "rationale": rationale,
                       "expires_in_hours": pol.expires_in_hours(policy_w)}
            pid = govern.queue_intent(store, now, wid, "approval", cur["version"], payload,
                                      {"allocations.default.caller_id": target})
        store.db.execute("UPDATE incidents SET action=? WHERE id=?",
                         (json.dumps({"kind": "rotate_caller_id", "proposal_id": pid,
                                      "bad": bad_cid, "to": best}), incident_id))
        store.audit(now, wid, "incident_remediation", f"inc{incident_id}",
                    {"proposal_id": pid, "route": "auto" if can_auto else "approval"})


def _with_alloc(cfg, dim, alloc):
    out = json.loads(json.dumps(cfg))
    out.setdefault("allocations", {}).setdefault("default", {})[dim] = alloc
    return out


def _next_attempt(store, wid, now):
    return 1 + store.db.execute("SELECT COUNT(*) FROM intents WHERE wid=?", (wid,)).fetchone()[0]


def _prompt_pipeline(api, store, wid, policy_w, incident_id, r, now):
    """halluc spike: candidates = previous known-good prompt, then LLM suggestions;
    validate (n>=200) until one passes the policy gate; propose with evidence."""
    open_prompt = store.db.execute(
        "SELECT COUNT(*) FROM proposals p JOIN intents i ON p.proposal_id=i.proposal_id "
        "WHERE p.wid=? AND p.status IN ('pending','approved') ", (wid,)).fetchone()[0]
    if open_prompt:
        return
    cur = api.get_config(wid)
    cur_prompt = cur["config"].get("prompt_version")
    # previous known-good prompt = the one most recently seen on calls BEFORE the current one
    prev_prompt = None
    prev = store.calls.execute(
        "SELECT prompt, MAX(ts) FROM calls WHERE wid=? AND prompt!=? GROUP BY prompt "
        "ORDER BY MAX(ts) DESC LIMIT 1", (wid, cur_prompt)).fetchone()
    if prev:
        prev_prompt = prev[0]

    creds = api.state().get("credits_remaining", 0)
    reserve = CREDIT_RESERVE_FRAC * float(store.get_meta("starting_credits", 0))  # D010
    candidates = []
    if prev_prompt:
        candidates.append(prev_prompt)
    # suggest-fixes is optional spend: skip it when it would dip into the reserve AND we
    # already have the previous known-good prompt to try; validation (essential) may dip.
    if len(candidates) < 3 and (creds - 3 >= reserve or not candidates):
        try:
            sug = api.suggest_fixes(wid, f"hallucination rate spiked to {r['observed']:.3f} "
                                    f"vs baseline {r['expected']:.3f} on {wid}")
            for s in sug.get("suggestions", []):
                p = s.get("prompt_version")
                if p and p != cur_prompt and p not in candidates \
                        and p in policy_w.get("options", {}).get("prompt_version", [p]):
                    candidates.append(p)
            creds = sug.get("credits_remaining", creds)
        except ApiError as e:
            log.warning("suggest-fixes failed: %s", e)
    gate = policy_w.get("governance", {}).get("min_validation_pass_rate", 0.97)
    for cand in candidates[:3]:
        if creds < math.ceil(VALIDATION_N / 100):
            log.warning("out of credits for validation; stopping pipeline")
            break
        try:
            val = api.validation_run(wid, cand, VALIDATION_N)
        except ApiError as e:
            log.warning("validation failed for %s: %s", cand, e)
            continue
        creds = val.get("credits_remaining", creds)
        store.audit(now, wid, "validation_run", val.get("validation_run_id"),
                    {"prompt": cand, "pass_rate": val.get("pass_rate"), "n": VALIDATION_N})
        if val.get("pass_rate", 0) >= gate:
            _propose_prompt(api, store, wid, policy_w, incident_id, cand, cur, val, r, now)
            return
    log.warning("no prompt candidate passed validation for %s", wid)


def _propose_prompt(api, store, wid, policy_w, incident_id, cand, cur, val, r, now):
    cfg = json.loads(json.dumps(cur["config"]))
    old = cfg.get("prompt_version")
    cfg["prompt_version"] = cand
    diff = {"prompt_version": {"from": old, "to": cand}}
    payload = {"workflow_id": wid, "base_version": cur["version"], "proposed_config": cfg,
               "change_summary": f"Replace prompt {old} -> {cand} to stop hallucination spike",
               "diff": diff,
               "affected_leads": store.db.execute(
                   "SELECT COUNT(*) FROM leads WHERE wid=? AND done=0", (wid,)).fetchone()[0],
               "dry_run": {"halluc_observed": r["observed"], "halluc_baseline": r["expected"],
                           "window_n": r["n"],
                           "validation": {"id": val["validation_run_id"],
                                          "pass_rate": val["pass_rate"], "n": val["n"]}},
               "impact_score": min(1.0, (r["observed"] - r["expected"]) * 10),
               "rationale": (f"Incident inc{incident_id}: hallucination rate {r['observed']:.3f} "
                             f"vs baseline {r['expected']:.3f} (z={r['z']:.1f}, n={r['n']}) after "
                             f"an external prompt change. Candidate {cand} passed validation at "
                             f"{val['pass_rate']:.3f} (gate {policy_w['governance']['min_validation_pass_rate']})."),
               "evidence": {"validation_run_id": val["validation_run_id"]},
               "expires_in_hours": pol.expires_in_hours(policy_w)}
    with store.db:
        pid = govern.queue_intent(store, now, wid, "approval", cur["version"], payload, diff)
        store.db.execute("UPDATE incidents SET action=? WHERE id=?",
                         (json.dumps({"kind": "prompt_change", "proposal_id": pid,
                                      "to": cand, "validation": val["validation_run_id"]}),
                          incident_id))
        store.audit(now, wid, "incident_remediation", f"inc{incident_id}",
                    {"proposal_id": pid, "prompt": cand})


def _verify_open_incidents(api, store, wid, policy_w, now, nowdt, state):
    rows = store.db.execute(
        "SELECT id, slice, metric, detected_ts, action FROM incidents WHERE wid=? AND "
        "resolved_ts IS NULL", (wid,)).fetchall()
    for iid, slice_, metric, detected_ts, action_j in rows:
        action = json.loads(action_j or "{}")
        # staged auto-rotation: keep stepping max_shift per tick until the bad cid is at 0
        if action.get("kind") == "rotate_caller_id":
            no_pending = not store.db.execute(
                "SELECT 1 FROM intents WHERE wid=? AND status='pending_send'", (wid,)).fetchone()
            if no_pending:
                r = {"observed": 0, "expected": 0, "z": 0, "n": 0, "effect": -1}
                cur_alloc = api.get_config(wid)["config"]["allocations"].get(
                    "default", {}).get("caller_id", {})
                if cur_alloc.get(action["bad"], 0) > 0.011:
                    _rotate_caller_id(api, store, wid, policy_w, iid, action["bad"],
                                      dict(r, observed=0.0, expected=0.0), now)
        hours = (nowdt - datetime.fromisoformat(detected_ts)).total_seconds() / 3600
        if hours < VERIFY_AFTER_H:
            continue
        cid = slice_.split("=")[1] if slice_.startswith("caller_id=") else None
        since = (nowdt - timedelta(hours=VERIFY_AFTER_H)).isoformat()[:13]
        rows_w = _window_counts(store, wid, since, cid)
        r = _zscore(store, wid, metric, slice_, rows_w)
        bad = r and abs(r["z"]) >= Z_THR and abs(r["effect"]) >= EFFECT_FLOOR and \
            ((metric == "halluc" and r["effect"] > 0) or (metric != "halluc" and r["effect"] < 0))
        if not bad:  # recovered, or traffic moved away (no data = fixed by rotation)
            with store.db:
                store.db.execute("UPDATE incidents SET resolved_ts=? WHERE id=?", (now, iid))
                store.audit(now, wid, "incident_resolved", f"inc{iid}",
                            {"metric": metric, "slice": slice_,
                             "post_window": (r or {"n": 0})})