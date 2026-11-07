"""Entrypoint: python -m controller <SIM_URL> [--state-dir DIR]

The loop (design.md section 3): advance -> ingest -> detect -> decide -> act.
Restart-safe at every point; a new world (different scenario or restarted sim) wipes state.
"""
import argparse
import logging
import sys
import time

from .api import Sim, ApiError
from .store import Store
from . import ingest, policy, detect, experiments, govern

log = logging.getLogger("main")

TICK_MINUTES = 15


def world_check(api: Sim, store: Store) -> dict:
    """Detect scenario change or sim restart: our cursor must not be ahead of the sim."""
    st = api.state()
    stored = store.get_meta("scenario")
    if stored and stored != st["scenario"]:
        log.warning("scenario changed (%s -> %s): resetting state", stored, st["scenario"])
        store.reset()
    elif int(store.get_meta("last_event_id", -1)) > st["last_event_id"]:
        log.warning("sim is behind our cursor (sim restarted): resetting state")
        store.reset()
    store.set_meta("scenario", st["scenario"])
    store.db.commit()
    return st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--state-dir", default="state")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    api = Sim(a.url)
    store = Store(a.state_dir)
    st = world_check(api, store)
    now = st["ts"]

    if store.get_meta("last_chunk") is None:
        ingest.bootstrap_history(api, store)
    else:  # restart: catch up on chunks we may have missed, then repair governance state
        nums = ingest.new_chunk_numbers(api, store)
        if nums:
            ingest.ingest_chunks(api, store, nums)
    policy.refresh(api, store, now)
    govern.reconcile(api, store, now)

    ticks = 0
    t0 = time.time()
    events = 0
    while not st.get("finished"):
        try:
            st = api.advance(TICK_MINUTES)
        except ApiError as e:
            if e.status == 409:  # finished
                break
            raise
        now = st["ts"]
        events += ingest.ingest_chunks(api, store, ingest.new_chunk_numbers(api, store, st))
        detect.step(store, now)
        experiments.step(api, store, now)
        govern.act(api, store, now)
        govern.poll_and_apply(api, store, now)
        ticks += 1
        if ticks % 96 == 0:  # once per sim-day: loop health (C14 minimal)
            with store.db:
                store.audit(now, "", "loop_health", f"tick{ticks}",
                            {"events_ingested": events, "wall_seconds": round(time.time() - t0, 1),
                             "credits_remaining": st.get("credits_remaining"),
                             "pending_proposals": store.db.execute(
                                 "SELECT COUNT(*) FROM proposals WHERE status='pending'").fetchone()[0]})
            log.info("day done: tick=%d events=%d credits=%s", ticks, events, st.get("credits_remaining"))
        if ticks % 96 == 0:
            policy.refresh(api, store, now)

    log.info("scenario finished at %s after %d ticks, %d events", now, ticks, events)
    return 0


if __name__ == "__main__":
    sys.exit(main())
