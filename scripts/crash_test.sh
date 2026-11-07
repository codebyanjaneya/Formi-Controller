#!/usr/bin/env bash
# Crash-recovery evidence (README deliverable 4).
# One public_02 world; the controller is killed at five different moments and restarted;
# the run must finish and scripts/check_invariants.py must pass.
# Usage: scripts/crash_test.sh [PORT]   (expects .venv to exist)
set -uo pipefail
cd "$(dirname "$0")/.."
PORT="${1:-8710}"
URL="http://127.0.0.1:$PORT"
STATE=state_crash
REPORT=reports/crash_recovery.md
if [ -f .venv/bin/python ]; then PY=.venv/bin/python; else PY=.venv/Scripts/python; fi

rm -rf "$STATE" runs/crash02
export PYTHONUTF8=1
echo "starting sim serve (public_02) on :$PORT ..."
$PY -m sim serve --scenario scenarios/public_02_incidents.yaml --run-dir runs/crash02 --port "$PORT" &
SIM_PID=$!
trap 'kill -9 $SIM_PID 2>/dev/null' EXIT
until curl -s -o /dev/null "$URL/health"; do sleep 2; done

{
  echo "# Crash-recovery evidence (public_02, one world, generated $(date -u +%FT%TZ))"
  echo
  echo "Controller killed at five moments (os._exit(9) at the named hook = kill -9 semantics),"
  echo "restarted each time with the same state dir, then run to completion."
  echo
} > "$REPORT"

run_until_crash () {
  local hook="$1"
  echo "## crash at: $hook" >> "$REPORT"
  CTRL_CRASH_HOOK="$hook" CTRL_CRASH_FLAG="$STATE/flag_$hook" \
    $PY -m controller "$URL" --state-dir "$STATE" >/dev/null 2>&1
  local code=$?
  if [ -f "$STATE/flag_$hook" ]; then
    echo "- crashed as planned (exit $code), flag written; restarting" >> "$REPORT"
  else
    echo "- hook never reached in this run (exit $code)" >> "$REPORT"
  fi
}

run_until_crash intent_written
run_until_crash proposal_pending
run_until_crash approved_before_apply
run_until_crash auto_pending

echo "## crash at: random (kill -9 after 15s)" >> "$REPORT"
$PY -m controller "$URL" --state-dir "$STATE" >/dev/null 2>&1 &
CPID=$!
sleep 15
if kill -9 "$CPID" 2>/dev/null; then
  echo "- killed -9 mid-run; restarting" >> "$REPORT"
else
  echo "- controller finished before the kill; continuing" >> "$REPORT"
fi
wait "$CPID" 2>/dev/null

echo "## final run to completion" >> "$REPORT"
$PY -m controller "$URL" --state-dir "$STATE" 2>&1 | grep -E "finished|peak memory" | sed 's/^/- /' >> "$REPORT"

echo >> "$REPORT"
echo "## invariants" >> "$REPORT"
echo '```' >> "$REPORT"
$PY scripts/check_invariants.py "$URL" "$STATE" >> "$REPORT" 2>&1
RC=$?
echo '```' >> "$REPORT"
echo "invariants exit code: $RC" >> "$REPORT"
echo "crash test done, invariants rc=$RC (report: $REPORT)"
exit $RC
