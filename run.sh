#!/usr/bin/env bash
# Usage: ./run.sh <SIM_URL>
# Starts the controller against a running simulator and runs until the scenario ends.
# Creates a venv on first use. State lives in ./state (wiped automatically on a new world).
set -euo pipefail
cd "$(dirname "$0")"

if [ -z "${1:-}" ]; then
  echo "usage: ./run.sh <SIM_URL>" >&2
  exit 2
fi

PY=python3
command -v python3 >/dev/null 2>&1 || PY=python
if [ ! -d .venv ]; then
  "$PY" -m venv .venv
fi
if [ -f .venv/bin/python ]; then VPY=.venv/bin/python; else VPY=.venv/Scripts/python; fi
"$VPY" -m pip install -q -r requirements.txt
exec "$VPY" -m controller "$1"
