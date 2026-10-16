"""Baseline v22 command-parameter compatibility tests."""
from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "database"))
from baseline_upgrade_engine import _upgrade_instance_evidence_parameters, _column_names


class InstanceEvidenceBaselineUpgradeTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.backend = SimpleNamespace(name="sqlite")
        self.db.execute(
            "CREATE TABLE agent_instance_commands (command_id TEXT PRIMARY KEY, action TEXT NOT NULL)"
        )
        self.db.execute(
            "INSERT INTO agent_instance_commands(command_id,action) VALUES ('existing','status')"
        )

    def tearDown(self):
        self.db.close()

    def test_additive_and_idempotent(self):
        _upgrade_instance_evidence_parameters(self.backend, self.db)
        _upgrade_instance_evidence_parameters(self.backend, self.db)
        self.assertIn("parameters_json", _column_names(self.backend, self.db, "agent_instance_commands"))
        row = self.db.execute(
            "SELECT command_id,action,parameters_json FROM agent_instance_commands"
        ).fetchone()
        self.assertEqual(("existing", "status", None), tuple(row))

    def test_legacy_action_check_still_blocks_evidence(self):
        """Track the remaining migration gap; adding a column is insufficient."""
        self.db.execute("DROP TABLE agent_instance_commands")
        self.db.execute(
            "CREATE TABLE agent_instance_commands ("
            "command_id TEXT PRIMARY KEY, "
            "action TEXT NOT NULL CHECK (action IN "
            "('status','doctor','start','stop','restart','remove')))"
        )
        self.db.commit()
        _upgrade_instance_evidence_parameters(self.backend, self.db)
        self.db.execute("INSERT INTO agent_instance_commands(command_id,action,parameters_json) VALUES ('evidence','systemd_lifecycle_evidence','{}')")
        self.assertIn('parameters_json', _column_names(self.backend, self.db, 'agent_instance_commands'))

    def test_legacy_schema_preserves_rows_indexes_and_foreign_keys(self):
        """Baseline v22 must not silently destroy existing relational metadata."""
        self.db.execute("DROP TABLE agent_instance_commands")
        self.db.execute("CREATE TABLE agents (id TEXT PRIMARY KEY)")
        self.db.execute("CREATE TABLE instances (id TEXT PRIMARY KEY)")
        self.db.execute("INSERT INTO agents VALUES ('agent-1')")
        self.db.execute("INSERT INTO instances VALUES ('instance-1')")
        self.db.execute(
            "CREATE TABLE agent_instance_commands ("
            "command_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, "
            "instance_id TEXT NOT NULL, action TEXT NOT NULL "
            "CHECK (action IN ('status','doctor','start','stop','restart','remove')), "
            "FOREIGN KEY(agent_id) REFERENCES agents(id) ON DELETE CASCADE, "
            "FOREIGN KEY(instance_id) REFERENCES instances(id) ON DELETE CASCADE)"
        )
        self.db.execute(
            "CREATE INDEX idx_agent_instance_commands_agent_status "
            "ON agent_instance_commands(agent_id,action)"
        )
        self.db.execute(
            "INSERT INTO agent_instance_commands VALUES "
            "('existing','agent-1','instance-1','status')"
        )
        before_fk = [tuple(row) for row in self.db.execute(
            "PRAGMA foreign_key_list(agent_instance_commands)"
        )]
        before_indexes = [row[1] for row in self.db.execute(
            "PRAGMA index_list(agent_instance_commands)"
        )]
        self.db.commit()
        _upgrade_instance_evidence_parameters(self.backend, self.db)
        self.assertEqual(before_fk, [tuple(row) for row in self.db.execute(
            "PRAGMA foreign_key_list(agent_instance_commands)"
        )])
        self.assertEqual(before_indexes, [row[1] for row in self.db.execute(
            "PRAGMA index_list(agent_instance_commands)"
        )])
        self.assertEqual(1, self.db.execute(
            "SELECT COUNT(*) FROM agent_instance_commands WHERE command_id='existing'"
        ).fetchone()[0])
        self.assertEqual([], self.db.execute("PRAGMA foreign_key_check").fetchall())

    def test_missing_table_fails_closed(self):
        self.db.execute("DROP TABLE agent_instance_commands")
        with self.assertRaisesRegex(Exception, "table is missing"):
            _upgrade_instance_evidence_parameters(self.backend, self.db)


if __name__ == "__main__":
    unittest.main()
