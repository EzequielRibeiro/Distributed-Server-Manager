"""Opt-in integration test against real systemd and disposable launcher fixture.

No real Minecraft files or services are used. Only a uniquely named unit in
/run/systemd/system and a TemporaryDirectory are created, both cleaned.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents/linux/runtime"))
from adapters.systemd import SystemdAdapter
from adapters.base import AdapterError
from minecraft_serverpack_migration_provisioning import _readiness_log_baseline, _wait_for_done


@unittest.skipUnless(
    os.environ.get("CAPIVARA_RUN_SYSTEMD_FINALIZATION_E2E") == "1"
    and hasattr(os, "geteuid") and os.geteuid() == 0,
    "requires explicit opt-in and root on disposable Linux systemd host",
)
class RealSystemdAdapterE2E(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dsm-pr981-adapter-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.iid = "pr855-adapter-" + uuid.uuid4().hex[:10]
        self.unit = "capivara-instance-" + self.iid + ".service"
        self.unitfile = Path("/run/systemd/system") / self.unit
        self.root = self.base / self.iid
        self.working = self.root / "runtime"
        (self.working / "logs").mkdir(parents=True)
        self.version = "26.1.2.109"
        canonical = self.working / "libraries/net/neoforged/neoforge" / self.version / "unix_args.txt"
        canonical.parent.mkdir(parents=True)
        canonical.write_text("-Xmx1G\n")
        self.launch_args = self.working / "capivara-launch.args"
        self.launch_args.write_bytes(canonical.read_bytes())
        control = self.root / ".dsm"
        control.mkdir()
        (control / "minecraft-serverpack-migration.json").write_text(
            json.dumps({"phase": "committed", "target_loader_version": self.version})
        )
        fixture = self.base / "fake_neoforge.py"
        fixture.write_text(
            "import pathlib,time\n"
            "p=pathlib.Path(" + repr(str(self.working / "logs/latest.log")) + ")\n"
            "with p.open('a') as f:\n"
            " f.write('[Server thread/INFO]: Done (0.1s)! For help, type help\\n')\n"
            " f.flush()\n"
            "time.sleep(40)\n"
        )
        self.unitfile.write_text(
            "[Unit]\nDescription=DSM PR981 isolated readiness fixture\n"
            "[Service]\nType=simple\nExecStart=" + sys.executable + " " + str(fixture)
            + "\nRestart=no\nTimeoutStopSec=3\n"
        )
        self.addCleanup(self.cleanup_unit)
        subprocess.run(["systemctl", "daemon-reload"], check=True, timeout=10)
        self.record = {
            "instance_id": self.iid,
            "environment_id": "minecraft.java.neoforge",
            "instance_state_root": str(self.root),
            "working_directory": str(self.working),
        }
        self.adapter = SystemdAdapter()

    def cleanup_unit(self):
        subprocess.run(["systemctl", "stop", self.unit], capture_output=True, timeout=10)
        self.unitfile.unlink(missing_ok=True)
        subprocess.run(["systemctl", "daemon-reload"], capture_output=True, timeout=10)
        subprocess.run(["systemctl", "reset-failed", self.unit], capture_output=True, timeout=10)

    def test_real_systemd_start_and_fresh_readiness(self):
        observed = self.adapter.status(self.record)
        self.assertTrue(observed["available"])
        self.assertEqual(observed["active_state"], "inactive")
        baseline = _readiness_log_baseline(self.working)
        self.adapter.start(self.record)
        self.assertEqual(self.adapter.status(self.record)["active_state"], "active")
        self.assertTrue(_wait_for_done(
            self.record, self.adapter, timeout_seconds=8, baseline=baseline
        ))

    def test_modified_launcher_rejected_before_service_start(self):
        self.launch_args.write_text("-Xmx4G\n")
        with self.assertRaisesRegex(AdapterError, "launcher"):
            self.adapter.start(self.record)
        self.assertEqual(self.adapter.status(self.record)["active_state"], "inactive")


if __name__ == "__main__":
    unittest.main()
