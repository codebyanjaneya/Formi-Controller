# Grade report — public_01_dev

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.340 | +2.1% | 0.239 | +0.5% | 0.498 | +1.5% | 6% | 56 (47) |
| nw_kyc | 0.432 | +19.0% | 0.281 | +15.9% | 0.595 | +0.7% | 0% | 27 (21) |
| nw_renewal | 0.420 | +0.2% | 0.263 | -0.3% | 0.552 | +1.1% | 0% | 49 (42) |
| ALL | 0.386 | +4.9% | 0.255 | +3.1% | 0.538 | +1.5% | 2% | 132 (110) |

## Changes applied by the controller

4 applied — neutral: 3, beneficial: 1

- ks_cancel v2 (controller_approved) dims=['voice'] engageΔ=+0.009 didΔ=+0.000 → **neutral**
- nw_renewal v2 (controller_approved) dims=['voice'] engageΔ=+0.001 didΔ=+0.000 → **neutral**
- nw_kyc v2 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.152 → **beneficial**
- nw_renewal v3 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.005 → **neutral**

## Governance

```
{
  "approval_requests": 3,
  "decisions": {
    "approved": 3,
    "expired": 0
  },
  "rejection_reasons": {},
  "applied_via_approval": 3,
  "auto_applied": 1,
  "auto_apply_rejected": 0,
  "apply_conflicts": 0,
  "lapsed": 0,
  "peak_requests_per_24h": {
    "nw_kyc": 1,
    "nw_renewal": 1,
    "ks_cancel": 1
  }
}
```

## Incidents

```
[]
```

## Decaying variants — share of in-population calls still on the variant, by day after onset

```
{}
```

Credits used: 0 · validation runs: 0 · LLM fix calls: 0