"""Test-only crash injection. In normal runs the env vars are unset and this is a no-op.

scripts/crash_test.sh sets CTRL_CRASH_HOOK=<point> and CTRL_CRASH_FLAG=<file>; the first
time execution passes the named point, the process dies with os._exit(9) — no cleanup, no
atexit, exactly like kill -9 — and the flag file stops it from firing again after restart.
"""
import os


def maybe_crash(point: str):
    if os.environ.get("CTRL_CRASH_HOOK") != point:
        return
    flag = os.environ.get("CTRL_CRASH_FLAG")
    if flag and not os.path.exists(flag):
        with open(flag, "w") as f:
            f.write(point)
        os._exit(9)
