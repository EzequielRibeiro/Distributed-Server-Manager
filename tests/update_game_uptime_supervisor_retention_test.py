"""Retention of pinned supervisors is read-only, exhaustive and fail-closed."""
from __future__ import annotations
import hashlib
from importlib.machinery import SourceFileLoader
import importlib.util
from pathlib import Path
import os
import pwd
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents/linux/runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))
from materializers.systemd import render_unit


def module_from(path, name):
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


retention = module_from(ROOT / "update-manager/game-uptime-supervisor-retention.py",
                        "dsm928_retention")
stage = module_from(ROOT / "update-manager/game-uptime-supervisor-stage.py",
                    "dsm928_retention_stage")


class PinnedRetentionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="dsm928-retention-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.versions = self.root / "versions"
        self.versions.mkdir(mode=0o700)
        self.pins = []
        for n in (1, 2, 3):
            source = self.root / f"source-{n}.py"
            source.write_text(f"print({n})\n")
            sha = hashlib.sha256(source.read_bytes()).hexdigest()
            self.pins.append(stage.stage_supervisor(
                source, self.versions, expected_sha256=sha))
        self.unit = "capivara-instance-dsm928-minecraft-001.service"
        self.spec = {
            "instance_id": "dsm928-minecraft-001", "agent_id": "fixture",
            "runtime_id": "minecraft.java.neoforge",
            "game_id": "minecraft",
            "environment_id": "minecraft.java.neoforge",
            "user": pwd.getpwuid(os.geteuid()).pw_name,
            "working_directory": str(self.root),
            "executable": "/usr/bin/sleep", "arguments": ["180"],
        }
        self.next_unit = render_unit(
            self.spec,
            pinned_supervisor_preview={
                "path": self.pins[1]["path"],
                "sha256": self.pins[1]["sha256"],
            })
        self.active = [{
            "unit": self.unit,
            "pid": 30001, "start_stamp": 19000001, "state": "active",
            "supervisor_path": self.pins[0]["path"],
        }]

    _DEFAULT = object()

    def plan(self, *, installed_units=_DEFAULT, running_units=_DEFAULT,
             expected_units=_DEFAULT):
        return retention.retention_plan(
            self.versions,
            installed_units={self.unit: self.next_unit} if installed_units is self._DEFAULT
            else installed_units,
            running_units=self.active if running_units is self._DEFAULT else running_units,
            expected_units=[self.unit] if expected_units is self._DEFAULT else expected_units,
        )

    def test_preserves_old_running_and_new_installed_and_never_deletes(self):
        before = {p.name: p.read_bytes() for p in self.versions.iterdir()}
        result = self.plan()
        self.assertTrue(result["inventory_consistent"], result["blockers"])
        self.assertIn(self.pins[0]["path"], result["protected_running_versions"])
        self.assertIn(self.pins[1]["path"], result["protected_installed_versions"])
        self.assertEqual(result["manual_review_only_unreferenced_versions"],
                         [self.pins[2]["path"]])
        self.assertEqual(result["retained_versions"],
                         sorted(p["path"] for p in self.pins))
        self.assertFalse(result["automatic_deletion_allowed"])
        self.assertFalse(result["live_no_drain_authorized"])
        self.assertEqual({p.name: p.read_bytes()
                          for p in self.versions.iterdir()}, before)

    def test_pid_change_or_missing_running_unit_blocks_review(self):
        for observed in (
            [{**self.active[0], "pid": 0}],
            [{**self.active[0], "start_stamp": 0}],
            [{**self.active[0], "state": "inactive"}],
            [],
            None,
        ):
            with self.subTest(observed=observed):
                result = self.plan(running_units=observed)
                self.assertFalse(result["inventory_consistent"])
                self.assertEqual(result["manual_review_only_unreferenced_versions"],
                                 [])
                self.assertFalse(result["automatic_deletion_allowed"])

    def test_malformed_installed_or_active_path_blocks(self):
        for installed in (
            {self.unit: "ExecStart=/usr/bin/python3 /opt/dsm/console_supervisor.py"},
            {},
            {self.unit: self.next_unit, "unexpected.service": self.next_unit},
        ):
            self.assertFalse(
                self.plan(installed_units=installed)["inventory_consistent"])
        for path in (
            "/opt/dsm/agents/linux/runtime/console_supervisor.py",
            str(self.versions / ("console-supervisor-" + "a" * 64 + ".py")),
        ):
            result = self.plan(
                running_units=[{**self.active[0], "supervisor_path": path}])
            self.assertFalse(result["inventory_consistent"])
            self.assertFalse(result["automatic_deletion_allowed"])

    def test_corrupted_and_symlinked_supervisor_block(self):
        victim = Path(self.pins[0]["path"])
        victim.chmod(0o644)
        victim.write_bytes(b"corrupted")
        victim.chmod(0o444)
        result = self.plan()
        self.assertIn("corrupt_versioned_supervisor_file", result["blockers"])
        self.assertFalse(result["automatic_deletion_allowed"])
        victim.unlink()
        victim.symlink_to(self.root / "source-1.py")
        result = self.plan()
        self.assertIn("unsafe_versioned_supervisor_file", result["blockers"])

    def test_duplicate_expected_or_duplicate_running_units_block(self):
        self.assertIn("expected_unit_inventory_invalid",
                      self.plan(expected_units=[self.unit, self.unit])["blockers"])
        result = self.plan(running_units=self.active * 2)
        self.assertIn("duplicate_running_unit_observation", result["blockers"])

    def test_unknown_new_file_fails_closed_without_unlink(self):
        strange = self.versions / "unrecognized-release-supervisor.txt"
        strange.write_text("do not delete")
        result = self.plan()
        self.assertIn("unexpected_version_directory_entry", result["blockers"])
        self.assertEqual(strange.read_text(), "do not delete")
        self.assertFalse(result["automatic_deletion_allowed"])


if __name__ == "__main__":
    unittest.main()
