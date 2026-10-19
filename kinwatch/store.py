"""SQLite event store for KinWatch. One file, no server."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .ring_client import HistoryEvent

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id            TEXT PRIMARY KEY,      -- Ring history event id
    device_id     TEXT NOT NULL,
    device_name   TEXT,
    event_type    TEXT NOT NULL,         -- Ring's type (on_demand, motion, ding...)
    start_ms      INTEGER NOT NULL,
    end_ms        INTEGER,
    ring_labels   TEXT,                  -- JSON list of Ring cv_detections
    kw_label      TEXT,                  -- KinWatch's own label (person/package/vehicle/none)
    description   TEXT,                  -- one-line Bedrock vision description
    snapshot_path TEXT,
    raw           TEXT NOT NULL,
    seen_at       TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_events_start ON events(start_ms);
CREATE TABLE IF NOT EXISTS alerts (
    key        TEXT PRIMARY KEY,         -- Alert.key, so each alert is sent once
    rule       TEXT NOT NULL,
    severity   TEXT NOT NULL,
    title      TEXT NOT NULL,
    message    TEXT NOT NULL,
    event_id   TEXT,
    at_ms      INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);
"""


class EventStore:
    def __init__(self, path: str | Path = "kinwatch.db"):
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(events)")}
        if "vision" not in cols:  # migrate day-1 databases
            self.conn.execute("ALTER TABLE events ADD COLUMN vision TEXT")
            self.conn.commit()

    def add_if_new(self, ev: HistoryEvent, device_name: str | None = None) -> bool:
        """Insert the event; return True only if we had not seen it before."""
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO events (id, device_id, device_name, event_type, start_ms,"
            " end_ms, ring_labels, raw) VALUES (?,?,?,?,?,?,?,?)",
            (ev.id, ev.device_id, device_name, ev.event_type, ev.start_ms, ev.end_ms,
             json.dumps(ev.cv_labels), json.dumps(ev.raw)),
        )
        self.conn.commit()
        return cur.rowcount == 1

    def annotate(self, event_id: str, *, kw_label: str | None = None,
                 description: str | None = None, snapshot_path: str | None = None,
                 vision: dict | None = None) -> None:
        self.conn.execute(
            "UPDATE events SET kw_label=COALESCE(?, kw_label),"
            " description=COALESCE(?, description), snapshot_path=COALESCE(?, snapshot_path),"
            " vision=COALESCE(?, vision) WHERE id=?",
            (kw_label, description, snapshot_path,
             json.dumps(vision) if vision is not None else None, event_id),
        )
        self.conn.commit()

    def unlabelled_pictures(self) -> list[sqlite3.Row]:
        return list(self.conn.execute(
            "SELECT * FROM events WHERE (snapshot_path LIKE '%.jpg' OR snapshot_path LIKE '%.png')"
            " AND vision IS NULL ORDER BY start_ms"))

    def record_alert(self, alert) -> bool:
        """Store an alert; True only the first time this alert key is seen."""
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO alerts (key, rule, severity, title, message, event_id, at_ms)"
            " VALUES (?,?,?,?,?,?,?)",
            (alert.key, alert.rule, alert.severity, alert.title, alert.message,
             alert.event_id, alert.at_ms))
        self.conn.commit()
        return cur.rowcount == 1

    def get(self, event_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()

    def alerts(self, limit: int = 50) -> list[sqlite3.Row]:
        return list(self.conn.execute(
            "SELECT * FROM alerts ORDER BY created_at DESC LIMIT ?", (limit,)))

    def events_between(self, start_ms: int, end_ms: int) -> list[sqlite3.Row]:
        return list(self.conn.execute(
            "SELECT * FROM events WHERE start_ms BETWEEN ? AND ? ORDER BY start_ms",
            (start_ms, end_ms)))

    def without_media(self) -> list[sqlite3.Row]:
        return list(self.conn.execute(
            "SELECT * FROM events WHERE snapshot_path IS NULL OR snapshot_path LIKE '%.mp4'"
            " ORDER BY start_ms"))

    def recent(self, limit: int = 20) -> list[sqlite3.Row]:
        return list(self.conn.execute(
            "SELECT * FROM events ORDER BY start_ms DESC LIMIT ?", (limit,)))
