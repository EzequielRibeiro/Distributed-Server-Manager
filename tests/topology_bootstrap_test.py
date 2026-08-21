#!/usr/bin/env python3
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class InitialTopologyBootstrapTest(unittest.TestCase):
    def test_creates_region_and_datacenter_idempotently(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "capivara.db"
            env = dict(os.environ)
            env["DSM_DATABASE_DRIVER"] = "sqlite"
            env["DSM_DATABASE"] = str(db)

            subprocess.run(
                [sys.executable, str(ROOT / "database/manager.py"), "--root", str(ROOT), "--database", str(db), "init"],
                env=env,
                check=True,
                stdout=subprocess.DEVNULL,
            )

            command = [
                sys.executable,
                str(ROOT / "database/topology_bootstrap.py"),
                "--root", str(ROOT),
                "--region-id", "br-sudeste",
                "--region-name", "Brasil Sudeste",
                "--region-country-code", "BR",
                "--datacenter-id", "limeira-dc01",
                "--datacenter-name", "Limeira DC 01",
                "--datacenter-city", "Limeira",
                "--datacenter-country-code", "BR",
            ]
            subprocess.run(command, env=env, check=True, stdout=subprocess.DEVNULL)
            subprocess.run(command, env=env, check=True, stdout=subprocess.DEVNULL)

            with sqlite3.connect(db) as connection:
                region = connection.execute(
                    "SELECT name,country_code FROM regions WHERE id=?", ("br-sudeste",)
                ).fetchone()
                datacenter = connection.execute(
                    "SELECT region_id,name,city FROM datacenters WHERE id=?", ("limeira-dc01",)
                ).fetchone()

            self.assertEqual(region, ("Brasil Sudeste", "BR"))
            self.assertEqual(datacenter, ("br-sudeste", "Limeira DC 01", "Limeira"))


if __name__ == "__main__":
    unittest.main()
