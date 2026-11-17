#!/usr/bin/env python3
"""DayZ community-map acquisition, Agent reconciliation, and rollback in a private sandbox.

Executes real Linux Agent filesystem/validation/discovery code, but deliberately
stubs external downloads, security scanner, and privileged service operations.
It is NOT a substitute for a dedicated running DayZ Agent/server homologation.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for sub in ("agents/common", "core", "database", "dashboard", "agents/linux/runtime"):
    sys.path.insert(0, str(ROOT / sub))
sys.path.insert(0, str(ROOT))


class DayZMapAgentReconciliationSandboxTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="dsm1067-agent-reconcile-")
        cls.root = Path(cls.temp.name)
        cls.old_env = {key: os.environ.get(key) for key in
                       ("CAPIVARA_AGENT_STATE_DIR", "CAPIVARA_GAME_DATA_ROOT")}
        os.environ["CAPIVARA_AGENT_STATE_DIR"] = str(cls.root / "agent-state")
        os.environ["CAPIVARA_GAME_DATA_ROOT"] = str(cls.root / "game-data")
        import instance_runtime
        import content_client
        import dayz_operation_client
        from dayz_management import current_mission, discover_missions
        from content_activation_runtime import project_runtime_spec
        cls.runtime = instance_runtime
        cls.client = content_client
        cls.ops = dayz_operation_client
        cls.current_mission = staticmethod(current_mission)
        cls.discover_missions = staticmethod(discover_missions)
        cls.project_runtime_spec = staticmethod(project_runtime_spec)
        assert cls.client.STATE_ROOT == cls.root / "agent-state"
        assert cls.client.GAME_DATA_ROOT == cls.root / "game-data"

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()
        for key, previous in cls.old_env.items():
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous

    def setUp(self):
        self.calls = []
        self.resolved = {}
        clean = {"security_state": "clean", "engine": "fixture", "matches": []}
        self.patches = [
            patch.object(self.client, "require_clean", return_value=clean),
            patch.object(self.client, "apply_activation_snapshots", return_value=[]),
            patch.object(self.runtime, "status", return_value={"observed_state": "stopped"}),
            patch.object(self.runtime, "doctor", return_value={"ready": True}),
            patch.object(self.runtime, "lifecycle",
                         side_effect=lambda _config, _iid, action: self.calls.append(action)),
            patch.object(self.client, "resolve_source", side_effect=self._resolve),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])

    def _resolve(self, provider, artifact, stage, game_data_root):
        if provider == "local":
            path = Path(game_data_root) / str(artifact.get("package_id") or "")
            resolved = path.resolve()
            resolved.relative_to(Path(game_data_root).resolve())
            return resolved
        return self.resolved[str(artifact["url"])]

    def _instance(self, iid):
        game = self.root / iid / "game"
        state = self.root / iid / "state"
        config = state / "config" / "serverDZ.cfg"
        config.parent.mkdir(parents=True)
        (game / "mpmissions" / "dayzOffline.chernarusplus").mkdir(parents=True)
        config.write_text('class Missions { class DayZ { template="dayzOffline.chernarusplus"; }; };\n',
                          encoding="utf-8")
        binary = game / "stub-only.bin"
        binary.write_bytes(b"test-only: never executed")
        record = {
            "instance_id": iid, "agent_id": "agent-1067-sandbox", "game_id": "dayz",
            "adapter": "systemd", "working_directory": str(game), "path": str(game),
            "instance_state_root": str(state), "config_path": str(config),
            "arguments": ["-config=" + str(config)], "executable": str(binary),
            "desired_state": "stopped",
        }
        self.runtime.register_instance(record)
        self.assertTrue(str(self.runtime._instance_path(iid)).startswith(str(self.root)))
        return record

    @staticmethod
    def _archive(*missions):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as z:
            for name in missions:
                z.writestr("Mission Files/" + name + "/init.c", "void main() {}\n")
                z.writestr("Mission Files/" + name + "/db/types.xml", "<types/>\n")
        return output.getvalue()

    def _cmd(self, iid, provider, blob, *, rev=1, variant="", dependencies=None):
        artifact = {"provider": provider, "archive": True, "filename": "example-map.zip"}
        if provider == "local":
            rel = f"quarantine/{iid}/transfer-test/example-map.zip"
            source = self.client.GAME_DATA_ROOT / rel
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(blob)
            artifact.update({"package_id": rel, "ephemeral_upload": True})
        else:
            url = f"https://example.invalid/maps/{iid}-{rev}.zip"
            source = self.root / iid / f"fixture-{rev}.zip"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(blob)
            self.resolved[url] = source
            artifact["url"] = url
        marker = {"name": "Generic Example"}
        if variant:
            marker["mission_path"] = "Mission Files/" + variant
        return {
            "instance_id": iid, "content_id": "dayz-map:generic-example",
            "game_id": "dayz", "content_type": "map",
            "provider": provider, "artifact": artifact,
            "target": "maps/generic-example", "desired_state": "installed",
            "activation_state": "disabled", "version": str(rev),
            "revision": rev, "checksum": f"test-checksum-{rev}-{provider}",
            "metadata": {"community_map": marker},
            "dependencies": list(dependencies or []),
        }

    def _install(self, cmd):
        reports = self.client.apply_content_commands(
            {"agent_id": "agent-1067-sandbox"}, [cmd])
        self.assertEqual(len(reports), 1)
        self.assertTrue(str(self.client._state_path(cmd["instance_id"],cmd["content_id"])).startswith(str(self.root)))
        return reports[0]

    def test_github_https_and_upload_archives_materialize_without_restart(self):
        for provider in ("github", "http-archive", "local"):
            with self.subTest(provider=provider):
                iid = "sandbox-" + provider
                self._instance(iid)
                cmd = self._cmd(iid, provider, self._archive("regular.example", "hardcore.example"))
                result = self._install(cmd)
                self.assertEqual(result["status"], "applied", result.get("last_error"))
                managed = Path(result["managed_path"])
                self.assertTrue((managed / "Mission Files" / "regular.example" / "init.c").is_file())
                self.assertTrue((managed / "Mission Files" / "hardcore.example" / "init.c").is_file())
                self.assertEqual(self.calls, [], "Map preparation must never stop/start DayZ")
                projected = self.ops._record_with_prepared_maps(self.runtime.get_instance(iid), iid)
                found = self.discover_missions(projected)
                self.assertIn("regular.example", [m["id"] for m in found["missions"]])
                self.assertIn("hardcore.example", [m["id"] for m in found["missions"]])
                self.assertEqual(self.current_mission(projected), "dayzOffline.chernarusplus")

    def test_specific_mission_and_existing_workshop_dependency_survive_agent_state(self):
        iid = "sandbox-specific"
        record = self._instance(iid)
        dep = "steam-workshop:77777"
        self.client._write(self.client._state_path(iid, dep), {
            "instance_id": iid, "content_id": dep, "game_id": "dayz",
            "content_type": "workshop", "status": "applied",
            "installed_version": "1", "security_state": "clean",
        })
        cmd = self._cmd(iid, "local", self._archive("regular.example", "hardcore.example"),
                        variant="hardcore.example", dependencies=[dep])
        report = self._install(cmd)
        self.assertEqual(report["status"], "applied", report.get("last_error"))
        self.assertEqual(report["community_map"]["mission_path"], "Mission Files/hardcore.example")
        self.assertEqual(report["dependencies"], [dep])
        prepared = self.ops._record_with_prepared_maps(record, iid)
        self.assertEqual(prepared["_dayz_prepared_map_content"]["hardcore.example"],
                         ["dayz-map:generic-example", dep])
        self.assertEqual([m["id"] for m in prepared["content_dayz_community_missions"]],
                         ["hardcore.example"])
        self.assertEqual(self.calls, [])

    def test_bad_update_keeps_last_valid_map_and_reports_rollback(self):
        iid = "sandbox-failed-update"
        self._instance(iid)
        old = self._cmd(iid, "github", self._archive("regular.example"))
        before = self._install(old)
        self.assertEqual(before["status"], "applied", before.get("last_error"))
        old_file = Path(before["managed_path"]) / "Mission Files/regular.example/init.c"
        initial = old_file.read_bytes()
        invalid = self._cmd(iid, "github", b"not-an-archive", rev=2)
        report = self._install(invalid)
        self.assertEqual(report["status"], "rolled_back")
        self.assertEqual(report["installed_version"], "1")
        self.assertEqual(report["applied_revision"], 1)
        self.assertEqual(report["community_map"], old["metadata"]["community_map"])
        self.assertEqual(old_file.read_bytes(), initial)
        self.assertEqual(self.calls, [])

    def test_explicit_failed_mission_change_recovers_original_mission(self):
        iid = "sandbox-switch-rollback"
        record = self._instance(iid)
        cmd = self._cmd(iid, "local", self._archive("regular.example", "hardcore.example"))
        installed = self._install(cmd)
        self.assertEqual(installed["status"], "applied", installed.get("last_error"))
        config = self.root / iid / "state/config/serverDZ.cfg"
        self.assertIn("dayzOffline.chernarusplus", config.read_text(encoding="utf-8"))

        # A controlled materializer failure must trigger DayZ rollback logic.
        with (patch.object(self.ops, "status", return_value={"observed_state": "stopped"}),
              patch.object(self.ops.privileged_materialization, "materialize",
                           side_effect=[RuntimeError("synthetic materializer failure"), None]),
              patch.object(self.ops, "_repair_hybrid_file_access", return_value=None)):
            with self.assertRaisesRegex(RuntimeError, "rolled back"):
                self.ops._change_mission(
                    {"agent_id": "agent-1067-sandbox"}, record, iid,
                    {"mission": "hardcore.example", "content_mode": "disable",
                     "persistence_mode": "fresh"},
                )
        self.assertEqual(self.current_mission(record), "dayzOffline.chernarusplus")
        self.assertIn("dayzOffline.chernarusplus", config.read_text(encoding="utf-8"))
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
