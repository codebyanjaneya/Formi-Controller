# Step 5 — cohort & experiment sizing analysis (public_01_dev)

Source: 14 days of **history** events (187k lines) downloaded over HTTP (`/events/chunks?kind=history`) from a throwaway serve run (`runs/probe02`). Scripts: `scratch/fetch_history.py`, `scratch/analyze_history.py`.

> **Important caveat:** history ran under the **default config** (W1 / V1 / P1 everywhere; only caller_id had a D1/D2 mix, nw_kyc was D1-only). So this data tells us **which lead features separate people**, NOT which variant wins. Variant winners can only come from experiments we run ourselves. Also, history is pre-start data: if the scenario has mid-run drift/decay, these rates are a starting point, not a constant.

## 1. Volumes (per workflow, per day)

| workflow | dials/day | connected/day | pickup | engagement | leads/campaign | primary KPI |
|---|---|---|---|---|---|---|
| ks_cancel | 4653 | 1159 | 0.249 | 0.501 | 1500 | engagement_rate |
| nw_kyc | 1944 | 507 | 0.261 | 0.592 | 700 | **pickup_rate** |
| nw_renewal | 3486 | 942 | 0.270 | 0.542 | 1100 | engagement_rate |

Primary KPI from `/workflows`: nw_renewal and ks_cancel optimize **engagement** (guardrail: pickup must not drop >2pp); nw_kyc optimizes **pickup** (guardrail: engagement must not drop >2pp).

## 2. Returning persons (repeat person_id across campaigns)

| workflow | persons | in >1 campaign | share |
|---|---|---|---|
| ks_cancel | 15,226 | 4,489 | 29% |
| nw_kyc | 7,980 | 1,527 | 19% |
| nw_renewal | 9,774 | 3,844 | 39% |

A large minority of leads are the **same people called again** — matches `daily_batch.returning_share` in policy (0.4 / 0.2 / 0.3). Person-level memory (what they heard before) may matter.

## 3. Which features actually separate people (engagement, best vs worst value, two-proportion z-test)

| workflow | feature | best | rate | worst | rate | p-value | supported? |
|---|---|---|---|---|---|---|---|
| nw_renewal | age_band | 60+ | 0.622 | 18-30 | 0.459 | 1e-30 | **YES** |
| ks_cancel | age_band | 60+ | 0.556 | 18-30 | 0.423 | 4e-26 | **YES** |
| nw_kyc | age_band | 46-60 | 0.647 | 18-30 | 0.502 | 4e-18 | **YES** |
| nw_kyc | city_tier | 1 | 0.609 | 3 | 0.567 | 5e-3 | weak yes |
| all others (lang, value_band, most city_tier) | | | | | | p>0.1 | no |

- **age_band is the one feature that strongly separates engagement in all three workflows** (10–16pp spread). Everything else is flat or marginal.
- **city_tier separates pickup** visibly (tier 3 > tier 1 by 2–6pp in all workflows, huge n → statistically solid) and **hour-of-day separates pickup** (morning ≈0.27–0.30 vs 15:00–16:00 dip ≈0.21–0.25 and evening ≈0.22–0.26).
- caller_id D1 vs D2: no difference in history (≤0.8pp, within noise).
- **Multiple-comparisons warning:** we scanned 4 features × 3 workflows plus combos; at p<0.05 some "wins" would be false positives by construction. That is why the bar here is p<0.01, and why combo-level "patterns" below are treated as unverified until re-tested on live data.

## 4. Experiment sizing (two-proportion test, α=0.05, power 0.80, 50/50 split)

n/arm needed near these base rates: **engagement** ≈4300 (3pp), ≈1550 (5pp), ≈380 (10pp); **pickup** ≈3400 (3pp), ≈1250 (5pp), ≈330 (10pp). Days = n/arm ÷ (cohort denominator per day ÷ 2). Scenario length: **8 days**.

### Engagement KPI (denominator = connected calls/day)

| cohort | denom/day (ks / renewal) | days for 5pp | verdict |
|---|---|---|---|
| whole workflow ks_cancel | 1159 | 2.7 | OK — even 3pp in 7.5d |
| whole workflow nw_renewal | 942 | 3.3 | OK (3pp needs 9.1d — just over) |
| lang=hi (ks / renewal) | 692 / 473 | 4.5 / 6.5 | slow |
| age_band single values | 123–402 | 8–37 | **TOO SMALL** |
| any 2-feature combo | <400 | — | **TOO SMALL — all 179 combos** |

### Pickup KPI (denominator = dials/day; ~4x larger)

| cohort | denom/day | days for 5pp | verdict |
|---|---|---|---|
| whole workflow (all 3) | 1944–4653 | 0.5–1.3 | OK — 3pp in 1.5–3.6d |
| single feature values (most) | 470–2760 | 1–5 | OK/slow |
| 2-feature combos | mixed | — | 50 OK / 64 slow / 106 too small |

### Consequences for controller design

1. **A/B experiments are only affordable at workflow level** (and for pickup, at single-feature level). Fine-grained cohorts can never reach significance in 8 days.
2. **Cohorts should come from history priors, not from live tests**: age_band splits (engagement) and city_tier/hour (pickup) are already statistically established from 14 days of history — we can allocate differently per cohort from day 1 without burning test budget.
3. Detecting a **5pp** engagement move at workflow level takes ~3 days — we get at most 2 sequential experiment generations per workflow in the 8-day run. Choose arms carefully; prefer weighted splits over 100% flips (naive's harmful change showed why).
4. 3pp effects are effectively below our detection floor for engagement; don't chase them.

## 5. Carry-over check

`approval_decided` event confirmed for the **approved** case too (`status:"approved"`, reasons `[]`), not just rejected. Event stream is a complete source for approval outcomes.
