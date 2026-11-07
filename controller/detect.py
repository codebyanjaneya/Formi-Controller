"""Detection. Phase A: external config_changed watch only (feeds govern + experiments).
Phase C adds the sliced z-detectors and remediation (design.md section 6)."""
import json
import logging

from . import govern

log = logging.getLogger("detect")


def external_changes(store, since_audit_id: int) -> tuple[int, list[dict]]:
    """config_changed audit rows by actors other than us, after the given audit id."""
    rows = store.db.execute(
        "SELECT id, ts, wid, details FROM audit WHERE kind='config_changed' AND id>? ORDER BY id",
        (since_audit_id,)).fetchall()
    out, last = [], since_audit_id
    for aid, ts, wid, details in rows:
        last = aid
        d = json.loads(details)
        if d.get("actor") not in ("controller_approved", "controller_auto"):
            out.append({"ts": ts, "wid": wid, **d})
    return last, out


def step(store, now: str):
    """Phase A: watch for supervisor edits; mark our pending proposals stale (design.md section 7)."""
    cursor = int(store.get_meta("detect_audit_cursor", 0))
    cursor, externals = external_changes(store, cursor)
    for ev in externals:
        log.info("external config change on %s by %s: %s", ev["wid"], ev.get("actor"),
                 ev.get("changed_dims"))
        with store.db:
            govern.mark_stale_on_external_change(store, ev["wid"], now)
            store.audit(now, ev["wid"], "external_change_handled", "",
                        {"actor": ev.get("actor"), "changed_dims": ev.get("changed_dims")})
    with store.db:
        store.set_meta("detect_audit_cursor", cursor)
