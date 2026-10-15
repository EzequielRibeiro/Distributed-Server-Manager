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
        _upgrade_instance_evidence_parameters(self.backend, self.db)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                "INSERT INTO agent_instance_commands(command_id,action,parameters_json) "
                "VALUES ('evidence','systemd_lifecycle_evidence','{}')"
            )

    def test_missing_table_fails_closed(self):
        self.db.execute("DROP TABLE agent_instance_commands")
        with self.assertRaisesRegex(Exception, "table is missing"):
            _upgrade_instance_evidence_parameters(self.backend, self.db)


if __name__ == "__main__":
    unittest.main()
