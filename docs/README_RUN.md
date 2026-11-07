# Running, testing and operating the controller

Start here if you are new. Everything below works from a fresh clone on Linux/macOS/Windows
(Git Bash). Python 3.11+ required; no services besides Python and SQLite (file-based).

## Run the controller against a simulator

```bash
pip install -r requirements.txt                       # sim + controller deps (httpx)
python -m sim serve --scenario scenarios/public_01_dev.yaml --run-dir runs/mine01   # :8700
./run.sh http://127.0.0.1:8700                        # creates .venv on first use, runs to scenario end
```

`run.sh` needs no manual steps and exits 0 when the scenario finishes. Controller state lives
in `./state/` (`state.db` + `calls.db`); pointing it at a NEW world (different scenario, or a
restarted sim) wipes state automatically; restarting the controller against the SAME world
resumes exactly where it stopped. On Windows, prefix sim commands with `PYTHONUTF8=1`.

Grade a run (dev tool; the controller itself never reads `runs/`):

```bash
python -m sim baseline --scenario scenarios/public_01_dev.yaml --run-dir runs/base01
python -m sim grade --run runs/mine01 --baseline runs/base01 --out reports/public_01.md
```

## Tests

```bash
python -m pytest tests/ -q        # 27 tests: ids, winner stats, guardrail rule,
                                  # state machine, ingest idempotency, decay rollback
```

## Crash-recovery test (README deliverable 4)

```bash
bash scripts/crash_test.sh 8710   # one public_02 world; kill -9 at 5 moments + restarts;
                                  # writes reports/crash_recovery.md; exit 0 = invariants hold
```

## Load test (public_03, grading-box conditions)

```bash
python -m sim serve --scenario scenarios/public_03_load.yaml --run-dir runs/load03 --port 8701
docker run --rm --cpus=4 --memory=8g -v "$PWD:/app" -w /app python:3.11 \
  bash -c "pip install -q httpx; time python -m controller http://host.docker.internal:8701 --state-dir /tmp/s"
```

Measured: ~1.3 min per simulated day, ~11.3k events/s end-to-end, 801 MB peak
(reports/load_public_03.md).

## CLIs (all read the controller's own store — constraint 5.6)

| Command | Answers |
|---|---|
| `python -m controller.why why --workflow X [--since TS]` | every decision for X, in order |
| `python -m controller.why heard --person P [--day D]` | what P heard on each call, under which config version, who approved it |
| `python -m controller.summary [--day D]` | per workflow: changes (actor/dims/reason/route), running experiments, approver queue, incidents |
| `python -m controller.health [--url SIM]` | ingest lag, decisions/day, credit burn, open incidents, stuck proposals + page-on vs dashboard-only |

All CLIs take `--state-dir` (default `state`).

## Where things live

- `controller/` — the 11 modules (see docs/flow.md for the map); `controller/tuning.py` holds
  every threshold with its reason.
- `docs/design.md` — the architecture; `docs/decisions.md` — every decision D001…D021 with
  rejected alternatives; `docs/analysis_step5.md` / `step6.md` — the measurements the design
  stands on.
- `reports/` — final grade reports, crash evidence, load numbers (`reports/history/` keeps
  earlier phases).
