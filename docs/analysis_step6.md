# Step 6 — how incidents look in the HTTP data (public_02_incidents)

Passive observation: no config changes, 959×15-min ticks over 10 sim days (`runs/probe03`, throwaway). Baselines from **this scenario's own history** chunks. Scripts: `scratch/observe_run.py`, `scratch/analyze_probe03.py`. Scenario yaml never opened; all below is inferred from the API stream alone. Onsets estimated by max-likelihood single-changepoint fit on hourly series.

## Baselines (this scenario's history, 14 days)

| workflow | pickup | engagement | halluc rate | flow_adherence | day-to-day sd (pickup / eng / halluc) |
|---|---|---|---|---|---|
| ks_cancel | 0.253 | 0.504 | 0.0137 | 0.928 | 0.017 / 0.017 / 0.0029 |
| nw_kyc | 0.262 | 0.600 | 0.0165 | 0.928 | 0.034 / 0.017 / 0.0051 |
| nw_renewal | 0.274 | 0.554 | 0.0130 | 0.928 | 0.019 / 0.015 / 0.0035 |

**Hallucination false-positive floor: ~1.3–1.7% of connected calls is normal.** Day-to-day sd ~0.3–0.5pp. An alarm threshold below ~2.5–3% halluc rate would fire on noise.

## The three incidents, found from data alone

### 1. Caller-ID degradation (ks_cancel, D2)
- Step-fit onset: day 3 of the run, 10:00. `pickup[D2]` fell **0.251 → 0.084 (−16.7pp)**; D1 unchanged. Workflow-level pickup only fell −7.9pp (dilution ~50/50 across caller_ids).
- No other KPI moved from this incident (engagement/halluc/adherence flat until the separate prompt incident next day).
- **Lesson: slice detectors beat aggregate detectors** — the slice signal is 2× larger and names the cause directly.

### 2. Supervisor prompt change (ks_cancel)
- `config_changed` event: `actor:"supervisor"`, `changed_dims:["prompt_version"]`, proposal/approval ids `null` — day 4, 11:30. **The event itself is the primary signal; no inference needed.**
- Measured effects (step-fit onsets land exactly at the event hour): halluc rate **0.015 → 0.053 (×3.5)**, share of calls with flow_adherence<0.8 **0.004 → 0.039 (×10)**, engagement **−2.4pp**, pickup **unchanged**.
- Confirms the user-story risk: a bad prompt can also hurt engagement without tripping only the halluc detector — watch all four metrics after any prompt change.

### 3. Supervisor edit (nw_renewal, voice)
- `config_changed` event: `actor:"supervisor"`, `changed_dims:["voice"]` — day 6, 15:00.
- Measured effect: **nothing clearly visible.** Daily engagement/pickup/halluc stay within normal noise afterwards. Step-fit does not place any changepoint at the edit time.
- **Lesson: some external edits have no KPI signature.** The ONLY reliable way to notice them is the `config_changed` event (actor ≠ us). The controller must reconcile config state from events, and must reset/split its variant statistics at any external version change — otherwise its stats silently mix two configs.

## Detector simulation (rolling windows, z vs history baseline, |z|≥3, 24h cooldown)

| incident | window 1h | window 4h | window 24h |
|---|---|---|---|
| D2 pickup collapse (onset 10:00) | alarm +41 min (~100 dials into incident) | +41 min | +2 h |
| prompt → halluc spike (onset 11:30) | +8.5 h (but noisy pre-alarms) | **+2 h (~190 connected calls)** | +4 h |
| voice edit | never | never | never |

### False alarms observed (the real finding)

1. **Hour-of-day confound**: pickup has a real afternoon dip (≈0.21–0.25 at 15:00–16:00 vs 0.27–0.30 mornings). A flat all-day baseline made the 1h/4h pickup detector fire **almost every day around 16:00 in workflows with no incident**. A pickup detector must use hour-matched baselines (compare to the same hours in history) or day-over-day windows.
2. **Small-n spikes**: halluc detector fired on day 1 with n=30–35 and 3–4 flagged calls (p=0.086–0.133). For rare-event metrics, require a minimum count of positive events (≥5 flags) and n≥~300, not just n≥30.
3. **Baseline level mismatch**: nw_kyc live pickup ran ~0.24 vs history 0.262 with no incident — a ~2pp level offset. With 24h windows (huge n) even this tiny offset gives z≈−3 repeatedly. **z alone is not enough: require a minimum effect size too.**

### Trade-off summary

- 1h window: fastest (minutes) on big shifts, but worst false-alarm rate (diurnal + small-n).
- 4h window: best compromise — caught the big incidents within ~41 min–2 h, far fewer false alarms.
- 24h window: most stable, +2–4 h lag, but with big n it flags trivial offsets — needs an effect-size floor most of all.

## Generic detection rules (scenario-independent — nothing below references specific dates/workflows)

1. **External change watch**: any `config_changed` with an actor other than our own controller ⇒ record new version, **reset/segment all variant statistics at that boundary**, and run a before/after comparison on pickup, engagement, halluc rate and flow_adherence over the following hours. This catches supervisor changes even when KPIs don't move.
2. **Sliced anomaly detector** per workflow × dimension value (at least per caller_id), plus workflow aggregate: rolling ~4h window, alarm when ALL of:
   - |z| ≥ 3 vs an **hour-matched** history baseline,
   - |effect| ≥ max(3pp, 3× the metric's day-to-day sd),
   - window has ≥300 denominator events, and for rare-event metrics ≥5 positive events.
3. **Slow-drift check** (24h window, same effect-size floor) as a backstop for gradual decay the 4h window misses.
4. **Baseline recalibration**: treat history as the structural prior (hourly shape); recalibrate the level on live non-alarm data, since history level can be ~2pp off.
5. On alarm: prefer the most specific firing slice (e.g. one caller_id) as the cause; remediation = shift allocation away from the degraded option, which is exactly the dimension auto-apply often allows.
