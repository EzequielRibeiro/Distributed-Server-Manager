#!/usr/bin/env python3

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BootstrapTest(unittest.TestCase):
    def test_noninteractive_bootstrap_and_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "data" / "capivara.db"
            password_file = root / "admin-password"
            password_file.write_text("correct horse battery staple\n", encoding="utf-8")
            password_file.chmod(0o600)
            environment = os.environ.copy()
            environment.update({
                "DSM_ROOT": str(root),
                "DSM_DATABASE_DRIVER": "sqlite",
                "DSM_DATABASE": str(database),
            })
            command = [
                sys.executable,
                str(ROOT / "database" / "registry.py"),
                "--root", str(root),
                "bootstrap",
                "--admin", "root.admin",
                "--admin-password-file", str(password_file),
            ]
            first = subprocess.run(
                command, env=environment, check=True,
                capture_output=True, text=True,
            )
            second = subprocess.run(
                command, env=environment, check=True,
                capture_output=True, text=True,
            )
            for completed in (first, second):
                payload = json.loads(completed.stdout)
                self.assertEqual(payload["administrator"], "root.admin")
                self.assertNotIn("correct horse", completed.stdout)
            status = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "database" / "registry.py"),
                    "--root", str(root), "bootstrap-status",
                ],
                env=environment, check=True, capture_output=True, text=True,
            )
            self.assertEqual(json.loads(status.stdout), {
                "controllers": 1,
                "agents": 1,
                "customers": 0,
                "instances": 0,
            })


if __name__ == "__main__":
    unittest.main()
