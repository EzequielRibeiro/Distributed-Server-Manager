#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "core", ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend import DatabaseConfig
from backend_factory import create_backend
from universal_event_repository import UniversalEventRepository


def load_runtime(platform_name: str, filename: str, module_name: str):
    runtime = ROOT / "agents" / platform_name / "runtime"
    old_path = list(sys.path)
    sys.path.insert(0, str(runtime))
    try:
        spec = importlib.util.spec_from_file_location(module_name, runtime / filename)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path[:] = old_path


class YaraScanTelemetryAgentTest(unittest.TestCase):
    def _fake_scanner(self, root: Path) -> tuple[Path, Path]:
        rules = root / "rules.yar"
        rules.write_text("rule x { condition: false }\n", encoding="utf-8")
        binary = root / "yr"
        binary.write_text(
            """#!/usr/bin/env python3
import json,sys
target=sys.argv[-1]
if "scan-fail" in target:
 print("failure", file=sys.stderr); raise SystemExit(2)
if "blocked" in target:
 print(json.dumps({"path":target,"rules":[{"identifier":"blocked_rule","tags":["malware","block","infostealer"],"metadata":{"threat_name":"Example Stealer","malware_family":"ExampleFamily","category":"infostealer","description":"Example credential stealer"}}]}))
""",
            encoding="utf-8",
        )
        binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
        return binary, rules

    def test_clean_blocked_and_failed_emit_structured_lifecycle_events(self):
        for platform_name in ("linux", "windows"):
            with self.subTest(platform=platform_name), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                module = load_runtime(platform_name, "content_security.py", f"y4_security_{platform_name}_{id(self)}")
                binary, rules = self._fake_scanner(root)
                events = []
                context = {
                    "agent_id": "agent-y4",
                    "instance_id": "instance-y4",
                    "content_id": "content-y4",
                    "provider": "steam-workshop",
                    "game_id": "dayz",
                }
                env = {
                    "CAPIVARA_YARAX_BIN": str(binary),
                    "CAPIVARA_YARAX_RULES_PATH": str(rules),
                }
                with patch.dict(os.environ, env, clear=False), patch.object(
                    module, "emit_runtime_event",
                    side_effect=lambda state, event_type, **kwargs: events.append((event_type, kwargs)) or {},
                ):
                    clean = root / "clean.bin"; clean.write_bytes(b"clean")
                    blocked = root / "blocked.bin"; blocked.write_bytes(b"bad")
                    failed = root / "scan-fail.bin"; failed.write_bytes(b"x")
                    self.assertEqual(module.scan_content(clean, context=context)["security_state"], "clean")
                    self.assertEqual(module.scan_content(blocked, context=context)["security_state"], "blocked")
                    self.assertEqual(module.scan_content(failed, context=context)["security_state"], "scan_failed")

                types = [item[0] for item in events]
                self.assertEqual(types.count("YARAX_SCAN_STARTED"), 3)
                self.assertEqual(types.count("YARAX_SCAN_COMPLETED"), 2)
                self.assertEqual(types.count("YARAX_SCAN_FAILED"), 1)
                final = [item for item in events if item[0] == "YARAX_SCAN_COMPLETED" and item[1]["data"]["result"] == "blocked"][0]
                self.assertEqual(final[1]["agent_id"], "agent-y4")
                self.assertEqual(final[1]["instance_id"], "instance-y4")
                self.assertEqual(final[1]["data"]["content_id"], "content-y4")
                self.assertEqual(final[1]["data"]["provider"], "steam-workshop")
                self.assertEqual(final[1]["data"]["game_id"], "dayz")
                self.assertLessEqual(len(final[1]["data"]["matches"]), 50)
                self.assertIsInstance(final[1]["data"]["duration_ms"], int)
                match = final[1]["data"]["matches"][0]
                self.assertEqual(match["rule"], "blocked_rule")
                self.assertEqual(match["file_name"], "blocked.bin")
                self.assertEqual(match["relative_path"], "blocked.bin")
                self.assertEqual(match["detection_name"], "Example Stealer")
                self.assertEqual(match["threat_name"], "Example Stealer")
                self.assertEqual(match["malware_family"], "ExampleFamily")
                self.assertEqual(match["category"], "infostealer")
                self.assertNotIn(str(root), match["relative_path"])

    def test_content_client_passes_identity_context_to_scans(self):
        for platform_name in ("linux", "windows"):
            source = (ROOT / "agents" / platform_name / "runtime" / "content_client.py").read_text(encoding="utf-8")
            self.assertIn("def _security_context(config,cmd)", source)
            self.assertIn("require_clean(source,context=security_context)", source)
            self.assertIn("require_clean(payload,context=security_context)", source)
            self.assertIn("content_id", source)


class YaraScanTelemetryRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "db.sqlite")))
        self.backend.initialize()
        with self.backend.transaction() as connection:
            connection.execute("INSERT INTO nodes(id,name,role,status) VALUES (?,?,?,?)", ("controller-y4","Controller","controller","active"))
            connection.execute("INSERT INTO nodes(id,name,role,status) VALUES (?,?,?,?)", ("node-y4","Agent","agent","active"))
            connection.execute("INSERT INTO controllers(id,node_id,name,status) VALUES (?,?,?,?)", ("controller-y4","controller-y4","Controller","active"))
            connection.execute("INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)", ("agent-y4","controller-y4","node-y4","Agent","active"))
            connection.execute("INSERT INTO customers(id,controller_id,name,status) VALUES (?,?,?,?)", (1,"controller-y4","Customer","active"))
            connection.execute(
                "INSERT INTO instances(id,node_id,game_id,runtime_id,name,status,controller_id,agent_id,customer_id) VALUES (?,?,?,?,?,?,?,?,?)",
                ("instance-y4","node-y4","dayz","dayz.steam","DayZ","online","controller-y4","agent-y4",1),
            )
        self.repo = UniversalEventRepository(self.backend)
        self.repo.initialize()

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def _runtime(self, event_id: str, event_type: str, result: str):
        return {
            "schema_version": 1,
            "kind": "CapivaraRuntimeEvent",
            "event_id": event_id,
            "event_type": event_type,
            "occurred_at": "2026-09-18T22:00:00Z",
            "agent_id": "agent-y4",
            "instance_id": "instance-y4",
            "severity": "warning" if result != "clean" else "info",
            "data": {
                "content_id": "content-y4",
                "result": result,
                "duration_ms": 42,
                "engine_version": "1.20.0",
                "ruleset_version": "2026.09.18.1",
                "matches": [],
            },
        }

    def test_yarax_events_are_persisted_and_queryable(self):
        raw = [
            self._runtime("y4-start", "YARAX_SCAN_STARTED", ""),
            self._runtime("y4-clean", "YARAX_SCAN_COMPLETED", "clean"),
            self._runtime("y4-failed", "YARAX_SCAN_FAILED", "scan_failed"),
        ]
        result = self.repo.ingest_agent_events("agent-y4", raw)
        self.assertEqual(result["accepted"], 3)
        rows = self.repo.list_yarax_scans(agent_id="agent-y4", instance_id="instance-y4")
        self.assertEqual(len(rows), 3)
        self.assertEqual({row["event_type"] for row in rows}, {"YARAX_SCAN_STARTED","YARAX_SCAN_COMPLETED","YARAX_SCAN_FAILED"})
        self.assertTrue(all(row["data"].get("content_id") == "content-y4" for row in rows))


if __name__ == "__main__":
    unittest.main()
