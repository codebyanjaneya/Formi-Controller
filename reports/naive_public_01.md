# Grade report — public_01_dev

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.349 | +4.8% | 0.242 | +1.5% | 0.504 | +2.7% | 0% | 58 (47) |
| nw_kyc | 0.377 | +3.7% | 0.240 | -0.9% | 0.616 | +4.3% | 15% | 23 (21) |
| nw_renewal | 0.423 | +0.7% | 0.261 | -0.9% | 0.554 | +1.6% | 0% | 42 (42) |
| ALL | 0.380 | +3.0% | 0.248 | +0.2% | 0.543 | +2.5% | 3% | 123 (110) |

## Changes applied by the controller

6 applied — beneficial: 3, neutral: 2, harmful: 1

- nw_kyc v2 (controller_approved) dims=['voice'] engageΔ=+0.035 didΔ=+0.000 → **beneficial**
- nw_renewal v2 (controller_approved) dims=['voice'] engageΔ=+0.003 didΔ=+0.000 → **neutral**
- nw_kyc v3 (controller_approved) dims=['voice'] engageΔ=+0.034 didΔ=+0.000 → **beneficial**
- nw_renewal v3 (controller_approved) dims=['voice'] engageΔ=-0.002 didΔ=+0.000 → **neutral**
- nw_kyc v4 (controller_approved) dims=['voice'] engageΔ=-0.063 didΔ=+0.000 → **harmful**
- nw_kyc v5 (controller_approved) dims=['voice'] engageΔ=+0.069 didΔ=+0.000 → **beneficial**

## Governance

```
{
  "approval_requests": 16,
  "decisions": {
    "rejected": 2,
    "approved": 6,
    "expired": 7
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 2
  },
  "applied_via_approval": 6,
  "auto_applied": 0,
  "auto_apply_rejected": 0,
  "apply_conflicts": 0,
  "lapsed": 0,
  "peak_requests_per_24h": {
    "nw_renewal": 1,
    "nw_kyc": 1,
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