#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
if str(DASHBOARD) not in sys.path:
    sys.path.insert(0, str(DASHBOARD))

from instance_launch_profile import resolve_launch_profile


class InstanceLaunchProfileTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.catalog = self.root / "catalog" / "v2" / "runtimes" / "generic"
        self.catalog.mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def _write_runtime(self, *, runtime_id: str, engine: str, executable: str) -> None:
        payload = {
            "schema_version": 2,
            "kind": "RuntimeDefinition",
            "id": runtime_id,
            "game": "generic",
            "process": {
                "engine": engine,
                "executable": executable,
                "args": ["--safe"],
            },
        }
        (self.catalog / f"{runtime_id}.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_native_runtime_becomes_structured_systemd_profile(self):
        self._write_runtime(runtime_id="generic.native", engine="native", executable="server-bin")
        profile = resolve_launch_profile(self.root, "generic.native", expected_game_id="generic")
        self.assertEqual(profile["adapter"], "systemd")
        self.assertEqual(profile["launch"]["engine"], "native")
        self.assertEqual(profile["launch"]["executable"], "server-bin")
        self.assertEqual(profile["launch"]["arguments"], ["--safe"])

    def test_java_runtime_fails_closed_until_java_materializer_exists(self):
        self._write_runtime(runtime_id="generic.java", engine="java", executable="server.jar")
        with self.assertRaisesRegex(ValueError, "runtime engine is not supported"):
            resolve_launch_profile(self.root, "generic.java")

    def test_runtime_game_mismatch_is_rejected(self):
        self._write_runtime(runtime_id="generic.native", engine="native", executable="server-bin")
        with self.assertRaisesRegex(ValueError, "runtime game does not match instance"):
            resolve_launch_profile(self.root, "generic.native", expected_game_id="other")


if __name__ == "__main__":
    unittest.main()
