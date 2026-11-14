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
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents/linux/runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from materializers.base import MaterializerError
from materializers.systemd import render_unit

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
            "user": "disposable-instance-user",
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


if __name__ == "__main__":
    unittest.main()
