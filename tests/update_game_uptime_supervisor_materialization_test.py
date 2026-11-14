"""#928: native systemd materializer preview with a staged supervisor SHA.

No systemctl commands are issued. Neither unit file nor user installation is
changed. The actual SystemdMaterializer.apply/inspect code paths still call
render_unit(spec) without the preview-only keyword.
"""
from __future__ import annotations

import hashlib
import importlib.util
from importlib.machinery import SourceFileLoader
import os
import pwd
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents/linux/runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from materializers.base import MaterializerError
from materializers.systemd import render_unit, SystemdMaterializer, unit_path_for_spec

loader = SourceFileLoader(
    "dsm928_supervisor_stage_materializer_preview",
    str(ROOT / "update-manager/game-uptime-supervisor-stage.py"),
)
spec = importlib.util.spec_from_loader(loader.name, loader)
stage = importlib.util.module_from_spec(spec)
loader.exec_module(stage)


class PreviewPinnedMaterializerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dsm928-unit-preview-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = ROOT / "agents/linux/runtime/console_supervisor.py"
        self.digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.versions = self.root / "non-replaceable-preview"
        self.versions.mkdir(mode=0o700)
        self.stage = stage.stage_supervisor(
            self.source, self.versions, expected_sha256=self.digest)
        self.pin = {"path": self.stage["path"], "sha256": self.digest}
        self.instance = {
            "instance_id": "fixture-minecraft-005",
            "agent_id": "fixture-agent",
            "runtime_id": "minecraft.java.neoforge",
            "game_id": "minecraft",
            "environment_id": "minecraft.java.neoforge",
            "user": pwd.getpwuid(os.geteuid()).pw_name,
            "working_directory": str(self.root / "instance-runtime"),
            "executable": "/usr/bin/java",
            "arguments": ["-jar", "server.jar", "nogui"],
            "environment": {"DSM928_TEST_ONLY": "1"},
        }

    def test_preview_renders_pinned_execstart_without_writing_unit(self):
        generated = render_unit(self.instance, pinned_supervisor_preview=self.pin)
        self.assertIn('ExecStart="/usr/bin/python3" "' + self.pin["path"] + '"', generated)
        self.assertIn('"/usr/bin/java" "-jar" "server.jar" "nogui"', generated)
        self.assertIn("RuntimeDirectory=capivara-instance-console-fixture-minecraft-005", generated)
        self.assertNotIn("/opt/dsm/agents/linux/runtime/console_supervisor.py", generated)
        self.assertFalse(self.stage["systemd_integrated"])
        self.assertFalse(self.stage["live_no_drain_authorized"])
        self.assertFalse((self.root / "capivara-instance-fixture-minecraft-005.service").exists())

    def test_production_renderer_unaffected_without_explicit_preview_keyword(self):
        rendered = render_unit(self.instance)
        self.assertIn("/agents/linux/runtime/console_supervisor.py", rendered)
        # A request hidden in an instance spec cannot turn on the preview.
        self.assertEqual(render_unit({**self.instance,
                            "pinned_supervisor_preview": self.pin}), rendered)

    def test_preview_rejects_non_minecraft(self):
        dayz = {**self.instance, "game_id": "dayz", "environment_id": "dayz.stable"}
        with self.assertRaisesRegex(MaterializerError, "only for Minecraft"):
            render_unit(dayz, pinned_supervisor_preview=self.pin)

    def test_preview_rejects_hash_tampering_and_symlink(self):
        pinned = Path(self.pin["path"])
        pinned.chmod(0o644)
        pinned.write_bytes(b"tampered")
        with self.assertRaisesRegex(MaterializerError, "non-writable|digest mismatch"):
            render_unit(self.instance, pinned_supervisor_preview=self.pin)
        pinned.unlink()
        pinned.symlink_to(self.source)
        with self.assertRaisesRegex(MaterializerError, "missing or symlinked"):
            render_unit(self.instance, pinned_supervisor_preview=self.pin)

    def test_preview_rejects_writable_supervisor_and_parent(self):
        pinned = Path(self.pin["path"])
        pinned.chmod(0o644)
        with self.assertRaisesRegex(MaterializerError, "non-writable"):
            render_unit(self.instance, pinned_supervisor_preview=self.pin)
        pinned.chmod(0o444)
        self.versions.chmod(0o777)
        self.addCleanup(self.versions.chmod, 0o700)
        with self.assertRaisesRegex(MaterializerError, "unsafe pinned supervisor directory"):
            render_unit(self.instance, pinned_supervisor_preview=self.pin)

    def test_preview_rejects_replaceable_path_invalid_hash_and_injection(self):
        invalid = [
            {"path": "/opt/dsm/agents/linux/runtime/" +
                     "console-supervisor-" + self.digest + ".py",
             "sha256": self.digest},
            {"path": self.pin["path"] + "\nExecStart=/bin/sh",
             "sha256": self.digest},
            {"path": self.pin["path"], "sha256": "f" * 64},
            {"path": str(self.root / "other.py"), "sha256": self.digest},
            {"path": self.pin["path"], "sha256": self.digest, "extra": True},
        ]
        for value in invalid:
            with self.subTest(pin=value):
                with self.assertRaises(MaterializerError):
                    render_unit(self.instance, pinned_supervisor_preview=value)


    def test_preview_checks_actual_unprivileged_service_user_traversal(self):
        try:
            other = pwd.getpwnam("nobody")
        except KeyError:
            self.skipTest("nobody system account unavailable")
        if other.pw_uid == os.geteuid():
            self.skipTest("running with same uid as nobody")
        user_spec = {**self.instance, "user": "nobody"}
        with self.assertRaisesRegex(MaterializerError, "not traversable"):
            render_unit(user_spec, pinned_supervisor_preview=self.pin)
        self.root.chmod(0o711)
        self.versions.chmod(0o755)
        rendered = render_unit(user_spec, pinned_supervisor_preview=self.pin)
        self.assertIn("User=nobody", rendered)
        self.assertIn(self.pin["path"], rendered)
        self.versions.chmod(0o700)
        with self.assertRaisesRegex(MaterializerError, "not traversable"):
            render_unit(user_spec, pinned_supervisor_preview=self.pin)
        self.versions.chmod(0o755)
        Path(self.pin["path"]).chmod(0o400)
        with self.assertRaises(MaterializerError):
            render_unit(user_spec, pinned_supervisor_preview=self.pin)

    def test_preview_rejects_unknown_systemd_user(self):
        candidate = {**self.instance, "user": "dsm928-definitely-absent-no-such-user"}
        with self.assertRaisesRegex(MaterializerError, "unknown pinned supervisor service user"):
            render_unit(candidate, pinned_supervisor_preview=self.pin)



    def test_materializer_transition_plan_does_not_write_or_reload_systemd(self):
        unit_dir = self.root / "sandbox-units"
        unit_dir.mkdir()
        with mock.patch.dict(os.environ, {"CAPIVARA_INSTANCE_SYSTEMD_DIR": str(unit_dir)}):
            installed = unit_path_for_spec(self.instance)
            original = render_unit(self.instance)
            installed.write_text(original, encoding="utf-8")
            before = installed.read_bytes()
            digest = hashlib.sha256(before).hexdigest()
            materializer = SystemdMaterializer(
                runner=lambda *_args: self.fail("read-only transition attempted systemctl"))
            proposed = materializer.plan_pinned_transition(
                self.instance, pinned_supervisor_preview=self.pin,
                expected_installed_sha256=digest)
            self.assertEqual(proposed["installed_unit_sha256"], digest)
            self.assertTrue(proposed["change_proposed"])
            self.assertTrue(proposed["old_unit_snapshot_required"])
            self.assertTrue(proposed["retain_all_earlier_supervisor_versions"])
            self.assertFalse(proposed["unit_write_permitted"])
            self.assertFalse(proposed["live_no_drain_authorized"])
            self.assertEqual(installed.read_bytes(), before)
            # An explicit disposable write of the preview is NOT an authorized
            # production workflow, but reinspection must be idempotent.
            generated = render_unit(self.instance, pinned_supervisor_preview=self.pin)
            installed.write_text(generated, encoding="utf-8")
            new_digest = hashlib.sha256(installed.read_bytes()).hexdigest()
            again = materializer.plan_pinned_transition(
                self.instance, pinned_supervisor_preview=self.pin,
                expected_installed_sha256=new_digest)
            self.assertFalse(again["change_proposed"])
            self.assertFalse(again["unit_write_permitted"])

    def test_materializer_transition_rejects_stale_foreign_and_symlink_unit(self):
        unit_dir = self.root / "sandbox-units"
        unit_dir.mkdir()
        with mock.patch.dict(os.environ, {"CAPIVARA_INSTANCE_SYSTEMD_DIR": str(unit_dir)}):
            installed = unit_path_for_spec(self.instance)
            original = render_unit(self.instance)
            installed.write_text(original, encoding="utf-8")
            digest = hashlib.sha256(installed.read_bytes()).hexdigest()
            mat = SystemdMaterializer(
                runner=lambda *_args: self.fail("must never invoke systemctl"))
            with self.assertRaisesRegex(MaterializerError, "changed since baseline"):
                mat.plan_pinned_transition(
                    self.instance, pinned_supervisor_preview=self.pin,
                    expected_installed_sha256="0"*64)
            installed.write_text("[Service]\nExecStart=/bin/false\n")
            foreign_digest = hashlib.sha256(installed.read_bytes()).hexdigest()
            with self.assertRaisesRegex(MaterializerError, "unowned"):
                mat.plan_pinned_transition(
                    self.instance, pinned_supervisor_preview=self.pin,
                    expected_installed_sha256=foreign_digest)
            installed.unlink()
            installed.symlink_to(self.source)
            with self.assertRaisesRegex(MaterializerError, "missing or unsafe"):
                mat.plan_pinned_transition(
                    self.instance, pinned_supervisor_preview=self.pin,
                    expected_installed_sha256=digest)


if __name__ == "__main__":
    unittest.main()
