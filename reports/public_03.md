# Grade report — public_03_load

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| arav_cancel_2 | 0.354 | +3.7% | 0.243 | -0.3% | 0.517 | +3.3% | 28% | 414 (408) |
| arav_kyc_1 | 0.408 | +15.4% | 0.241 | +12.4% | 0.595 | -0.0% | 0% | 394 (370) |
| arav_renewal_0 | 0.420 | +4.4% | 0.264 | -0.2% | 0.566 | +4.2% | 20% | 432 (440) |
| kest_cancel_2 | 0.356 | +5.0% | 0.246 | +1.0% | 0.515 | +3.3% | 26% | 388 (411) |
| kest_kyc_1 | 0.429 | +21.4% | 0.250 | +16.7% | 0.598 | +0.7% | 0% | 374 (339) |
| kest_renewal_0 | 0.408 | +2.1% | 0.264 | +0.3% | 0.549 | +1.3% | 0% | 414 (433) |
| nort_cancel_2 | 0.355 | +4.8% | 0.243 | +0.1% | 0.519 | +4.1% | 27% | 359 (393) |
| nort_kyc_1 | 0.446 | +25.9% | 0.261 | +22.3% | 0.595 | -0.1% | 0% | 444 (323) |
| nort_renewal_0 | 0.414 | +2.3% | 0.264 | +0.2% | 0.557 | +1.7% | 11% | 413 (411) |
| tide_cancel_2 | 0.358 | +5.5% | 0.244 | +0.0% | 0.521 | +4.3% | 28% | 401 (407) |
| tide_kyc_1 | 0.399 | +12.8% | 0.237 | +10.6% | 0.591 | -0.1% | 0% | 383 (356) |
| tide_renewal_0 | 0.409 | +2.0% | 0.263 | -0.6% | 0.554 | +2.2% | 7% | 416 (438) |
| ALL | 0.396 | +8.6% | 0.252 | +4.6% | 0.557 | +2.4% | 11% | 4832 (4729) |

## Changes applied by the controller

27 applied — neutral: 12, beneficial: 15

- arav_cancel_2 v2 (controller_approved) dims=['voice'] engageΔ=+0.009 didΔ=+0.000 → **neutral**
- nort_cancel_2 v2 (controller_approved) dims=['voice'] engageΔ=+0.009 didΔ=+0.000 → **neutral**
- tide_cancel_2 v2 (controller_approved) dims=['voice'] engageΔ=+0.009 didΔ=+0.000 → **neutral**
- nort_renewal_0 v2 (controller_approved) dims=['voice'] engageΔ=+0.001 didΔ=+0.000 → **neutral**
- kest_renewal_0 v2 (controller_approved) dims=['voice'] engageΔ=+0.001 didΔ=+0.000 → **neutral**
- kest_cancel_2 v2 (controller_approved) dims=['voice'] engageΔ=+0.009 didΔ=+0.000 → **neutral**
- arav_renewal_0 v2 (controller_approved) dims=['voice'] engageΔ=+0.001 didΔ=+0.000 → **neutral**
- tide_renewal_0 v2 (controller_approved) dims=['voice'] engageΔ=+0.001 didΔ=+0.000 → **neutral**
- nort_kyc_1 v2 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.185 → **beneficial**
- kest_kyc_1 v2 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.195 → **beneficial**
- arav_kyc_1 v2 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.162 → **beneficial**
- tide_kyc_1 v2 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.184 → **beneficial**
- tide_cancel_2 v3 (controller_approved) dims=['voice'] engageΔ=+0.059 didΔ=+0.000 → **beneficial**
- arav_cancel_2 v3 (controller_approved) dims=['voice'] engageΔ=+0.060 didΔ=+0.000 → **beneficial**
- nort_cancel_2 v3 (controller_approved) dims=['voice'] engageΔ=+0.060 didΔ=+0.000 → **beneficial**
- tide_renewal_0 v3 (controller_approved) dims=['voice'] engageΔ=-0.001 didΔ=+0.000 → **neutral**
- nort_renewal_0 v3 (controller_approved) dims=['voice'] engageΔ=-0.001 didΔ=+0.000 → **neutral**
- arav_renewal_0 v3 (controller_approved) dims=['voice'] engageΔ=-0.001 didΔ=+0.000 → **neutral**
- kest_cancel_2 v3 (controller_approved) dims=['voice'] engageΔ=+0.059 didΔ=+0.000 → **beneficial**
- kest_renewal_0 v3 (controller_approved) dims=['voice'] engageΔ=-0.001 didΔ=+0.000 → **neutral**
- nort_renewal_0 v4 (controller_approved) dims=['welcome_message'] engageΔ=+0.030 didΔ=+0.000 → **beneficial**
- tide_renewal_0 v4 (controller_approved) dims=['welcome_message'] engageΔ=+0.030 didΔ=+0.000 → **beneficial**
- arav_renewal_0 v4 (controller_approved) dims=['welcome_message'] engageΔ=+0.030 didΔ=+0.000 → **beneficial**
- nort_kyc_1 v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.244 → **beneficial**
- arav_renewal_0 v5 (controller_approved) dims=['welcome_message'] engageΔ=+0.086 didΔ=+0.000 → **beneficial**
- arav_kyc_1 v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.239 → **beneficial**
- nort_renewal_0 v5 (controller_approved) dims=['welcome_message'] engageΔ=+0.086 didΔ=+0.000 → **beneficial**

## Governance

```
{
  "approval_requests": 32,
  "decisions": {
    "approved": 27,
    "rejected": 5,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 5
  },
  "applied_via_approval": 27,
  "auto_applied": 0,
  "auto_apply_rejected": 0,
  "apply_conflicts": 0,
  "lapsed": 0,
  "peak_requests_per_24h": {
    "arav_cancel_2": 1,
    "arav_kyc_1": 1,
    "arav_renewal_0": 3,
    "kest_cancel_2": 2,
    "kest_kyc_1": 1,
    "kest_renewal_0": 2,
    "nort_cancel_2": 1,
    "nort_kyc_1": 1,
    "nort_renewal_0": 2,
    "tide_cancel_2": 1,
    "tide_kyc_1": 1,
    "tide_renewal_0": 3
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