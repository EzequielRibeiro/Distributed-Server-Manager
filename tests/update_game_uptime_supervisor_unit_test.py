"""Unit evidence for pinned supervisor; fixture-only, no systemctl execution."""
from __future__ import annotations
import hashlib
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
loader = SourceFileLoader("dsm928_supervisor_unit", str(ROOT/"update-manager/game-uptime-supervisor-unit.py"))
spec = importlib.util.spec_from_loader(loader.name, loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)

class PinnedSupervisorUnitTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="dsm928-supervisor-unit-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.sha = hashlib.sha256(b"safe supervisor").hexdigest()
        self.path = self.root/("console-supervisor-"+self.sha+".py")
        self.path.write_bytes(b"safe supervisor")
        self.unit = "capivara-instance-minecraft-005.service"
        self.obs = {"main_pid": 555, "start_stamp": 987654,
                    "exec": "path=/usr/bin/python3 ; argv[]=/usr/bin/python3 "+str(self.path)+" --socket /tmp/isolated.sock -- /usr/bin/sleep 30 ; ignore_errors=no ;",
                    "fragment": "/etc/systemd/system/"+self.unit}

    def verify(self):
        return mod.verify_pinned_supervisor(self.unit, versions_dir=self.root,
                expected_sha256=self.sha, inspect=lambda unit:self.obs)

    def test_exact_pinned_path_returns_observation_not_authorization(self):
        value = self.verify()
        self.assertTrue(value["systemd_pinned_observed"])
        self.assertFalse(value["live_no_drain_authorized"])
        self.assertEqual(value["main_pid"], 555)

    def test_substring_not_accepted(self):
        self.obs["exec"] = "path=/usr/bin/python3 ; argv[]=/usr/bin/python3 "+str(self.path)+"-fake --socket /tmp/x ;"
        with self.assertRaises(mod.SupervisorUnitError): self.verify()

    def test_replaceable_controller_path_rejected(self):
        self.obs["exec"] += " /opt/dsm/agents/linux/runtime/helper.py"
        with self.assertRaises(mod.SupervisorUnitError): self.verify()

    def test_pid_invalid_rejected(self):
        self.obs["main_pid"] = 0
        with self.assertRaises(mod.SupervisorUnitError): self.verify()

    def test_bad_hash_rejected(self):
        self.path.write_bytes(b"tampered")
        with self.assertRaises(mod.SupervisorUnitError): self.verify()

    def test_symlink_rejected(self):
        self.path.unlink()
        self.path.symlink_to(self.root/"elsewhere")
        with self.assertRaises(mod.SupervisorUnitError): self.verify()

    def test_unknown_exec_format_rejected(self):
        self.obs["exec"] = "/usr/bin/python3 "+str(self.path)
        with self.assertRaises(mod.SupervisorUnitError): self.verify()

if __name__ == "__main__":
    unittest.main()
