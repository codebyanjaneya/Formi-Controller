"""SQLite state. Two files: state.db (hot loop state) and calls.db (insert-only per-call audit).

Crash-safety contract: the event cursor (meta.last_chunk / meta.last_event_id) commits in the
SAME transaction as the data derived from those events. calls.db is written before that commit;
re-inserting the same event after a rare crash-between-commits is prevented by INSERT OR IGNORE
on (event_id) — so both files stay consistent without cross-file transactions.
"""
import json
import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS workflows(wid TEXT PRIMARY KEY, policy TEXT, fetched_at TEXT);
CREATE TABLE IF NOT EXISTS config_versions(
  wid TEXT, version INT, actor TEXT, changed_dims TEXT, ts TEXT, config TEXT,
  PRIMARY KEY(wid, version));
CREATE TABLE IF NOT EXISTS campaigns(
  campaign_id TEXT PRIMARY KEY, wid TEXT, created_ts TEXT, leads INT, config_version INT);
CREATE TABLE IF NOT EXISTS leads(
  lead_id TEXT PRIMARY KEY, wid TEXT, person_id TEXT, campaign_id TEXT,
  lang TEXT, city_tier TEXT, age_band TEXT, value_band TEXT, done INT DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_leads_wid ON leads(wid, done);
CREATE TABLE IF NOT EXISTS agg_calls(
  wid TEXT, hour_ts TEXT, config_version INT, cohort_id TEXT,
  welcome TEXT, voice TEXT, caller_id TEXT, prompt TEXT,
  dials INT, connected INT, engaged INT, halluc INT, adher_lo INT, adher_sum REAL,
  PRIMARY KEY(wid, hour_ts, config_version, cohort_id, welcome, voice, caller_id, prompt));
CREATE TABLE IF NOT EXISTS baselines(
  wid TEXT, metric TEXT, slice TEXT, hour INT, rate REAL, n INT,
  PRIMARY KEY(wid, metric, slice, hour));
CREATE TABLE IF NOT EXISTS experiments(
  exp_id TEXT PRIMARY KEY, wid TEXT, dimension TEXT, cohort TEXT, arms TEXT,
  start_version INT, status TEXT, started_ts TEXT, decided_ts TEXT, winner TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS intents(
  proposal_id TEXT PRIMARY KEY, wid TEXT, kind TEXT, attempt INT, base_version INT,
  payload TEXT, status TEXT, created_ts TEXT, response TEXT);
CREATE TABLE IF NOT EXISTS proposals(
  proposal_id TEXT PRIMARY KEY, approval_id TEXT, wid TEXT, status TEXT, base_version INT,
  expires_at TEXT, apply_by TEXT, reasons TEXT, decided_ts TEXT);
CREATE TABLE IF NOT EXISTS incidents(
  id INTEGER PRIMARY KEY AUTOINCREMENT, wid TEXT, slice TEXT, metric TEXT,
  onset_ts TEXT, detected_ts TEXT, action TEXT, resolved_ts TEXT);
CREATE TABLE IF NOT EXISTS audit(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, wid TEXT, kind TEXT, ref TEXT, details TEXT);
CREATE TABLE IF NOT EXISTS detect_state(key TEXT PRIMARY KEY, consec INT, last_alarm TEXT);
CREATE TABLE IF NOT EXISTS baseline_scale(
  wid TEXT, metric TEXT, slice TEXT, factor REAL, updated_ts TEXT,
  PRIMARY KEY(wid, metric, slice));
"""

CALLS_SCHEMA = """
CREATE TABLE IF NOT EXISTS calls(
  event_id INT PRIMARY KEY, ts TEXT, wid TEXT, campaign_id TEXT, person_id TEXT, lead_id TEXT,
  attempt_no INT, cohort_id TEXT, config_version INT,
  welcome TEXT, voice TEXT, caller_id TEXT, prompt TEXT,
  connected INT, engaged INT, disposition TEXT, halluc INT, adher REAL);
CREATE INDEX IF NOT EXISTS idx_calls_person ON calls(person_id, ts);
"""


class Store:
    def __init__(self, state_dir: str):
        os.makedirs(state_dir, exist_ok=True)
        self.dir = state_dir
        self.db = sqlite3.connect(os.path.join(state_dir, "state.db"))
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)
        self.calls = sqlite3.connect(os.path.join(state_dir, "calls.db"))
        self.calls.execute("PRAGMA journal_mode=WAL")
        self.calls.execute("PRAGMA synchronous=NORMAL")
        self.calls.executescript(CALLS_SCHEMA)

    # --- meta ---
    def get_meta(self, key: str, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_meta(self, key: str, value):
        self.db.execute("INSERT INTO meta(key,value) VALUES(?,?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))

    def audit(self, ts: str, wid: str, kind: str, ref: str, details: dict):
        self.db.execute("INSERT INTO audit(ts,wid,kind,ref,details) VALUES(?,?,?,?,?)",
                        (ts, wid, kind, ref, json.dumps(details)))

    def reset(self):
        """New world detected: wipe everything (scenario changed or sim restarted)."""
        self.db.close()
        self.calls.close()
        for f in os.listdir(self.dir):
            os.remove(os.path.join(self.dir, f))
        self.__init__(self.dir)
