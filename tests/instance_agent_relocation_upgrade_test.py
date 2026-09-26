#!/usr/bin/env python3
"""Version 22 backfill for existing Baseline v2 installs (SQLite)."""
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend import DatabaseConfig
from backend_factory import create_backend
from baseline_upgrade_engine import apply_pending_upgrades, latest_upgrade_version


class AgentRelocationUpgradeTest(unittest.TestCase):
    def test_upgrade_v21_to_v22_creates_only_relocation_tables(self):
        with tempfile.TemporaryDirectory() as temp:
            backend = create_backend(DatabaseConfig(driver="sqlite", database=str(Path(temp) / "db.sqlite")))
            backend.initialize()
            with backend.connect() as c:
                c.execute("DROP TABLE instance_agent_relocation_port_holds")
                c.execute("DROP TABLE instance_agent_relocations")
                c.execute("DELETE FROM baseline_upgrades WHERE version=22")
                c.commit()
            with backend.transaction() as c:
                upgrades = apply_pending_upgrades(
                    backend, c, installed_checksum="different-baseline-checksum-after-v21",
                )
                self.assertEqual(upgrades, [22])
            with backend.connect() as c:
                rows = [r["name"] for r in c.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name IN ('instance_agent_relocations','instance_agent_relocation_port_holds')"
                )]
                self.assertCountEqual(rows, [
                    "instance_agent_relocations", "instance_agent_relocation_port_holds",
                ])
                self.assertEqual(
                    c.execute("SELECT max(version) AS v FROM baseline_upgrades").fetchone()["v"],
                    latest_upgrade_version(),
                )


if __name__ == "__main__":
    unittest.main()
