#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
if str(DATABASE) not in sys.path:
    sys.path.insert(0, str(DATABASE))

from baseline_upgrade_engine import (  # noqa: E402
    UPGRADES,
    _upgrade_alert_events_note_action,
    latest_upgrade_version,
)
from schema_baseline import load_schema_baseline  # noqa: E402


class AlertNoteBaselineContractTest(unittest.TestCase):
    def test_compiled_baselines_accept_note_for_every_supported_vendor(self):
        for backend in ("sqlite", "postgresql", "mysql", "mariadb"):
            with self.subTest(backend=backend):
                sql = load_schema_baseline(backend).sql
                start = sql.lower().index("create table alert_events")
                end = sql.lower().find("create table", start + 1)
                block = sql[start : end if end >= 0 else len(sql)]
                self.assertIn("'NOTE'", block)
                for action in (
                    "OPEN",
                    "REOPEN",
                    "ESCALATE",
                    "ACK",
                    "RESOLVE",
                    "SUPPRESS",
                    "NOTE",
                ):
                    self.assertIn(f"'{action}'", block)

    def test_upgrade_five_is_registered(self):
        self.assertEqual(5, latest_upgrade_version())
        self.assertEqual(5, UPGRADES[-1].version)
        self.assertEqual("alert_events_note_action", UPGRADES[-1].name)


class AlertNoteSQLiteUpgradeTest(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript(
            """
CREATE TABLE alerts (
    id TEXT PRIMARY KEY
);
CREATE TABLE alert_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (
        action IN ('OPEN','REOPEN','ESCALATE','ACK','RESOLVE','SUPPRESS')
    ),
    level TEXT NOT NULL CHECK (level IN ('INFO','WARNING','CRITICAL')),
    old_state TEXT,
    new_state TEXT NOT NULL CHECK (
        new_state IN ('OPEN','ACKNOWLEDGED','RESOLVED','SUPPRESSED')
    ),
    message TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ),
    FOREIGN KEY (alert_id) REFERENCES alerts(id) ON DELETE CASCADE
);
CREATE INDEX idx_alert_events_alert ON alert_events(alert_id);
CREATE TABLE alert_event_trigger_log(event_id INTEGER NOT NULL);
CREATE TRIGGER alert_events_test_trigger
AFTER INSERT ON alert_events
BEGIN
    INSERT INTO alert_event_trigger_log(event_id) VALUES (NEW.id);
END;
INSERT INTO alerts(id) VALUES ('alert-1');
INSERT INTO alert_events(
    alert_id,action,level,old_state,new_state,message
) VALUES ('alert-1','ACK','CRITICAL','OPEN','ACKNOWLEDGED','existing');
"""
        )
        self.backend = SimpleNamespace(name="sqlite")

    def tearDown(self):
        self.connection.close()

    def test_upgrade_preserves_rows_indexes_and_triggers_and_accepts_note(self):
        _upgrade_alert_events_note_action(self.backend, self.connection)

        row = self.connection.execute(
            "SELECT action,message FROM alert_events WHERE id=1"
        ).fetchone()
        self.assertEqual("ACK", row["action"])
        self.assertEqual("existing", row["message"])

        index_row = self.connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='index' AND name='idx_alert_events_alert'"
        ).fetchone()
        self.assertIsNotNone(index_row)

        trigger_row = self.connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='trigger' AND name='alert_events_test_trigger'"
        ).fetchone()
        self.assertIsNotNone(trigger_row)

        self.connection.execute(
            "INSERT INTO alert_events("
            "alert_id,action,level,old_state,new_state,message"
            ") VALUES (?,?,?,?,?,?)",
            (
                "alert-1",
                "NOTE",
                "CRITICAL",
                "ACKNOWLEDGED",
                "ACKNOWLEDGED",
                "operator note",
            ),
        )
        note = self.connection.execute(
            "SELECT action,message FROM alert_events ORDER BY id DESC LIMIT 1"
        ).fetchone()
        self.assertEqual("NOTE", note["action"])
        self.assertEqual("operator note", note["message"])

        trigger_count = self.connection.execute(
            "SELECT COUNT(*) AS count FROM alert_event_trigger_log"
        ).fetchone()["count"]
        self.assertEqual(2, trigger_count)

        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "INSERT INTO alert_events("
                "alert_id,action,level,new_state,message"
                ") VALUES (?,?,?,?,?)",
                ("alert-1", "BOGUS", "CRITICAL", "ACKNOWLEDGED", "invalid"),
            )

        # A database that already accepts NOTE must not be rebuilt again.
        _upgrade_alert_events_note_action(self.backend, self.connection)
        self.assertEqual(
            2,
            self.connection.execute(
                "SELECT COUNT(*) AS count FROM alert_events"
            ).fetchone()["count"],
        )


if __name__ == "__main__":
    unittest.main()
