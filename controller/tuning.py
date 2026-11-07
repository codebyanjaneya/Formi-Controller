"""Every tuning constant in one place, with its reason (D018).

These are OUR caution/statistics settings — scenario-independent by construction. Everything
that describes a workflow (options, KPIs, guardrails, governance limits, validation gates)
comes from the policy API at runtime and must never appear here.
"""

# --- experiments (controller/experiments.py) ---
CHAMPION_SHARE = 0.7       # champion keeps 70% during a test: exploration risk capped at 30%
CHALLENGER_TOTAL = 0.3     # 30% TOTAL to challengers, split evenly (D010/D015)
PROMOTE_SHARE = 0.8        # winner gets 80%; the 20% residual feeds the decay watch (D007)
ALPHA = 0.05               # family-wise false-winner bound per experiment
LOOKS = 2                  # judge only at min-n(10pp) and min-n(5pp); measured A/A 1-4% (D015)
MIN_N_FLOOR = 200          # never judge any arm below this, whatever the power math says
HARM_FLOOR = 0.03          # a challenger this much worse (and significant) ends the test early
EXP_NEED_DAYS = 2          # don't start a test with less scenario time than this
DECAY_WINDOW_H = 48        # decay watch compares winner vs residual over this window
DECAY_MIN_RESIDUAL = 100   # min residual-arm n before a decay verdict

# --- detection (controller/detect.py) ---
Z_THR = 3.0                # |z| needed vs hour-matched baseline (D004)
EFFECT_FLOOR = 0.03        # ignore shifts under 3pp: below our action resolution (step-6 sd)
MIN_N = 300                # window denominator floor; small-n spikes false-alarmed in step 6
MIN_POS = 5                # rare metrics (halluc) also need >= this many positive events
PERSIST = 2                # consecutive ticks before an alarm: multiple-comparisons control
COOLDOWN_H = 24            # per-series alarm cooldown
WINDOW_H = 4               # fast window: caught both public_02 incidents in <= 4h
DRIFT_WINDOW_H = 24        # slow-drift backstop
RECALIB_H = 72             # baseline LEVEL recalibrated on this much live data daily (D016)
RECALIB_CLAMP = (0.85, 1.15)  # recalibration can't absorb a real step change

# --- remediation safety rails (D016: each learned from a measured failure) ---
ROTATE_SLICE_MARGIN = 0.02   # slice must be >=2pp worse than aggregate, else it's not the cause
ROTATE_MAX_SLICE_SHARE = 0.85  # a slice carrying >85% of traffic IS the aggregate: no rotation
ROTATE_HEALTHY_MIN_DIALS = 200  # target needs this much recent traffic ("proven healthy")
MAX_AUTO_PER_DAY = 8         # auto-apply brake; the ping-pong storm shipped 55/day unbraked
VALIDATION_N = 200           # per step-5: n=50 pass_rate noise flips the 0.97 gate
VERIFY_AFTER_H = 12          # post-remediation verification window
CREDIT_RESERVE_FRAC = 0.2    # of STARTING credits; optional spends stop here (D010)
