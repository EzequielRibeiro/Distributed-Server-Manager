#!/usr/bin/env python3

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANAGER = ROOT / "database" / "manager.py"


class DatabaseRestoreCliTest(unittest.TestCase):
    def test_restore_requires_confirmation_and_restores_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "data" / "capivara.db"
            backup = root / "backups" / "capivara.db"
            base = [
                sys.executable, str(MANAGER), "--root", str(root),
                "--driver", "sqlite", "--database", str(database),
            ]
            subprocess.run(base + ["init"], check=True, capture_output=True)
            subprocess.run(
                base + ["backup", str(backup)], check=True, capture_output=True,
            )
            with closing(sqlite3.connect(database)) as connection:
                connection.execute(
                    "INSERT INTO nodes(id,name,role) VALUES (?,?,?)",
                    ("after-backup", "After Backup", "agent"),
                )
                connection.commit()
            refused = subprocess.run(
                base + ["restore", str(backup)],
                capture_output=True, text=True,
            )
            self.assertEqual(refused.returncode, 1)
            self.assertIn("--confirm-restore", refused.stderr)
            with closing(sqlite3.connect(database)) as connection:
                self.assertIsNotNone(connection.execute(
                    "SELECT 1 FROM nodes WHERE id='after-backup'"
                ).fetchone())
            restored = subprocess.run(
                base + ["restore", str(backup), "--confirm-restore"],
                capture_output=True, text=True,
            )
            self.assertEqual(restored.returncode, 0, restored.stderr)
            self.assertEqual(json.loads(restored.stdout)["kind"], "DatabaseRestore")
            with closing(sqlite3.connect(database)) as connection:
                self.assertIsNone(connection.execute(
                    "SELECT 1 FROM nodes WHERE id='after-backup'"
                ).fetchone())


if __name__ == "__main__":
    unittest.main()
