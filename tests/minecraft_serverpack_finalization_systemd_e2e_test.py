"""Optional transient systemd-worker E2E; NEVER touches a Minecraft instance.

Execute on an isolated Linux host:
 CAPIVARA_RUN_SYSTEMD_FINALIZATION_E2E=1 python3 -m unittest \
    tests.minecraft_serverpack_finalization_systemd_e2e_test -v

Uses TemporaryDirectory Agent records, distinct transient service names and
the production worker code. No service installation, Agent enrollment or
modpack download.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
import uuid

from tests.minecraft_serverpack_finalization_subprocess_e2e_test import (
    FinalizationWorkerProcessE2E, IID, WORKER,
)


@unittest.skipUnless(
    os.environ.get("CAPIVARA_RUN_SYSTEMD_FINALIZATION_E2E") == "1",
    "systemd E2E requires explicit opt-in on an isolated host",
)
class SystemdWorkerE2E(FinalizationWorkerProcessE2E):
    def run_transient(self, *, flags=None, instance=IID) -> subprocess.CompletedProcess:
        if not shutil.which("systemd-run"):
            self.skipTest("systemd-run is missing")
        unit = "dsm-pr981-worker-e2e-" + uuid.uuid4().hex[:12]
        env = self.env | (flags or {})
        args = [
            "systemd-run", "--unit=" + unit, "--collect", "--wait", "--pipe",
            "--property=RuntimeMaxSec=20",
            "--setenv=CAPIVARA_AGENT_STATE_DIR=" + str(self.state),
            "--setenv=CAPIVARA_SERVERPACK_FINALIZATION_RECONCILE_INSTANCE=" +
                env.get("CAPIVARA_SERVERPACK_FINALIZATION_RECONCILE_INSTANCE", ""),
            "--setenv=CAPIVARA_SERVERPACK_FINALIZATION_RECONCILE=" +
                env.get("CAPIVARA_SERVERPACK_FINALIZATION_RECONCILE", "0"),
            "--setenv=CAPIVARA_SERVERPACK_FINALIZATION_RECOVER=0",
            sys.executable, str(WORKER), str(self.config), instance,
        ]
        return subprocess.run(args, capture_output=True, text=True, timeout=35)

    def test_systemd_unit_reconciles_then_replays_without_mutation(self):
        first = self.run_transient()
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        self.assertIn("Finished with result: success", first.stderr)
        initial = self.operation.read_bytes()
        self.assertEqual(json.loads(initial)["status"], "completed")
        second = self.run_transient()
        self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
        self.assertEqual(self.operation.read_bytes(), initial)

    def test_systemd_unit_denies_disabled_reconciliation(self):
        denied = self.run_transient(
            flags={"CAPIVARA_SERVERPACK_FINALIZATION_RECONCILE": "0"}
        )
        self.assertNotEqual(denied.returncode, 0)
        self.assertEqual(json.loads(self.operation.read_text())["status"],
                         "finalization_pending")

    def test_systemd_unit_denies_changed_archive_evidence(self):
        digest = self.detail["finalization"]["sha256"]
        journal = self.hist / digest[:24] / "minecraft-serverpack-migration.json"
        journal.write_text("tampered")
        denied = self.run_transient()
        self.assertNotEqual(denied.returncode, 0)
        self.assertEqual(json.loads(self.operation.read_text())["status"],
                         "finalization_pending")


if __name__ == "__main__":
    unittest.main()
