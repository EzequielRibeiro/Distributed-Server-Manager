#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
PRIVILEGED = ROOT / "agents" / "linux" / "privileged"
for path in (RUNTIME, PRIVILEGED):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import instance_runtime
import materialize_instance
import runtime_materialization
from adapters.base import InstanceRuntimeAdapter
from materializers.systemd import SystemdMaterializer, render_unit, unit_path_for_spec
from runtime_spec import RuntimeSpecError, validate_runtime_spec


class FakeAdapter(InstanceRuntimeAdapter):
    name = "systemd"

    def __init__(self, running=False):
        self.running = running

    def status(self, instance):
        return {"adapter": "systemd", "available": True, "active_state": "active" if self.running else "inactive", "running": self.running}

    def start(self, instance):
        self.running = True
        return {"action": "start", "changed": True, "state": self.status(instance)}

    def stop(self, instance):
        self.running = False
        return {"action": "stop", "changed": True, "state": self.status(instance)}

    def restart(self, instance):
        self.running = True
        return {"action": "restart", "changed": True, "state": self.status(instance)}

    def doctor(self, instance):
        return {"status": "healthy", "ready": True, "findings": []}


class B8RuntimeMaterializationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.systemd = self.root / "systemd"
        self.work = self.root / "instance"
        self.work.mkdir()
        self.executable = self.work / "server-bin"
        self.executable.write_text("binary placeholder", encoding="utf-8")
        self.old_systemd = os.environ.get("CAPIVARA_INSTANCE_SYSTEMD_DIR")
        os.environ["CAPIVARA_INSTANCE_SYSTEMD_DIR"] = str(self.systemd)
        self.old_paths = (instance_runtime.STATE_DIR, instance_runtime.INSTANCE_DIR, instance_runtime.RESULT_DIR, instance_runtime.HISTORY_DIR)
        instance_runtime.STATE_DIR = self.root / "state"
        instance_runtime.INSTANCE_DIR = instance_runtime.STATE_DIR / "instances"
        instance_runtime.RESULT_DIR = instance_runtime.STATE_DIR / "instance-results"
        instance_runtime.HISTORY_DIR = instance_runtime.STATE_DIR / "instance-command-history"
        self.config = {"agent_id": "agent-one"}

    def tearDown(self):
        instance_runtime.STATE_DIR, instance_runtime.INSTANCE_DIR, instance_runtime.RESULT_DIR, instance_runtime.HISTORY_DIR = self.old_paths
        if self.old_systemd is None:
            os.environ.pop("CAPIVARA_INSTANCE_SYSTEMD_DIR", None)
        else:
            os.environ["CAPIVARA_INSTANCE_SYSTEMD_DIR"] = self.old_systemd
        self.temp.cleanup()

    def spec(self, **overrides):
        value = {
            "instance_id": "instance-one",
            "agent_id": "agent-one",
            "runtime_id": "runtime-one",
            "adapter": "systemd",
            "working_directory": str(self.work),
            "executable": str(self.executable),
            "arguments": ["--port=25000", "value with spaces"],
            "environment": {"CAPIVARA_TEST": "yes"},
            "user": "capivara-instance",
            "desired_state": "running",
        }
        value.update(overrides)
        return value

    def test_runtime_spec_is_structured_and_agent_owned(self):
        normalized = validate_runtime_spec(self.spec(), expected_agent_id="agent-one")
        self.assertEqual(normalized["kind"], "CapivaraInstanceRuntimeSpec")
        with self.assertRaises(RuntimeSpecError):
            validate_runtime_spec(self.spec(agent_id="agent-two"), expected_agent_id="agent-one")
        with self.assertRaises(RuntimeSpecError):
            validate_runtime_spec(self.spec(executable="server-bin"), expected_agent_id="agent-one")
        with self.assertRaises(RuntimeSpecError):
            validate_runtime_spec(self.spec(arguments=["ok\nExecStart=/bin/sh"]), expected_agent_id="agent-one")

    def test_systemd_materializer_is_idempotent_and_refuses_foreign_unit(self):
        calls = []
        runner = lambda command, timeout: (calls.append(list(command)) or (0, "", ""))
        spec = validate_runtime_spec(self.spec(), expected_agent_id="agent-one")
        materializer = SystemdMaterializer(runner=runner)
        first = materializer.apply(spec)
        second = materializer.apply(spec)
        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])
        self.assertEqual(calls, [["systemctl", "daemon-reload"]])
        content = unit_path_for_spec(spec).read_text(encoding="utf-8")
        self.assertIn("X-Capivara-Instance=instance-one", content)
        self.assertIn('"value with spaces"', content)
        unit_path_for_spec(spec).write_text("[Service]\nExecStart=/bin/false\n", encoding="utf-8")
        with self.assertRaises(Exception):
            materializer.apply(spec)

    def test_materialize_registers_instance_and_emits_structured_event(self):
        class Materializer:
            def apply(self, spec):
                return {"action": "materialize", "changed": True, "state": {"exists": True, "owned": True}}
        original = runtime_materialization.resolve_materializer
        runtime_materialization.resolve_materializer = lambda spec: Materializer()
        try:
            result = runtime_materialization.materialize(self.config, self.spec())
        finally:
            runtime_materialization.resolve_materializer = original
        self.assertTrue(result["instance"]["materialized"])
        self.assertEqual(instance_runtime.get_instance("instance-one")["runtime_id"], "runtime-one")
        events = (instance_runtime.STATE_DIR / "events" / "instance-runtime.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(json.loads(events[-1])["type"], "INSTANCE_RUNTIME_READY")

    def test_reconcile_converges_desired_running_state(self):
        normalized = validate_runtime_spec(self.spec(), expected_agent_id="agent-one")
        instance_runtime.register_instance({**normalized, "observed_state": "stopped", "materialized": True})

        class Materializer:
            def inspect(self, spec):
                return {"exists": True, "owned": True, "matches": True}
        adapter = FakeAdapter(running=False)
        old_materializer = runtime_materialization.resolve_materializer
        old_adapter = runtime_materialization.resolve_adapter
        runtime_materialization.resolve_materializer = lambda spec: Materializer()
        runtime_materialization.resolve_adapter = lambda spec: adapter
        try:
            result = runtime_materialization.reconcile(self.config, "instance-one")
        finally:
            runtime_materialization.resolve_materializer = old_materializer
            runtime_materialization.resolve_adapter = old_adapter
        self.assertTrue(result["changed"])
        self.assertEqual(result["observed_state"], "running")
        self.assertEqual(instance_runtime.get_instance("instance-one")["desired_state"], "running")

    def test_inventory_observes_live_adapter_state_instead_of_stale_cache(self):
        adapter = FakeAdapter(running=False)
        original = instance_runtime.resolve_adapter
        instance_runtime.resolve_adapter = lambda spec: adapter
        try:
            instance_runtime.register_instance({
                "instance_id": "instance-live",
                "agent_id": "agent-one",
                "game_id": "dayz",
                "environment_id": "dayz.stable",
                "adapter": "systemd",
                "observed_state": "running",
            })
            inventory = instance_runtime.list_instances(self.config)
        finally:
            instance_runtime.resolve_adapter = original
        self.assertEqual(inventory[0]["observed_state"], "stopped")

    def test_private_seed_directory_allows_agent_content_root_and_rejects_escape(self):
        state = self.root / "agent-state"
        content = state / "game-data" / "minecraft" / "bedrock"
        content.mkdir(parents=True)
        (content / "bedrock_server").write_text("binary", encoding="utf-8")
        (content / "bedrock_server").chmod(0o755)
        storage_root = self.root / "instances"
        instance_root = storage_root / "instance-seed"
        working = instance_root / "runtime"
        spec = {
            "instance_id": "instance-seed",
            "instance_state_root": str(instance_root),
            "working_directory": str(working),
            "profile_context": {"content_root": str(content)},
            "seed_files": [],
            "seed_directories": [{"source": str(content), "target": str(working)}],
            "bind_paths": [],
            "writable_directories": [str(working)],
        }
        account = type("Account", (), {"pw_uid": os.getuid(), "pw_gid": os.getgid()})()
        agent_account = type("Account", (), {"pw_uid": os.getuid(), "pw_gid": os.getgid()})()
        agent_group = type("Group", (), {"gr_gid": os.getgid()})()
        original_state = materialize_instance.STATE_DIR
        materialize_instance.STATE_DIR = state
        try:
            with mock.patch.object(materialize_instance.os, "chown", return_value=None), \
                 mock.patch.object(materialize_instance.pwd, "getpwnam", return_value=agent_account), \
                 mock.patch.object(materialize_instance.grp, "getgrnam", return_value=agent_group):
                materialize_instance._prepare_private_state(spec, account, storage_root)
            self.assertTrue((working / "bedrock_server").is_file())
            self.assertEqual(stat.S_IMODE((working / "bedrock_server").stat().st_mode), 0o700)
            (working / "bedrock_server").chmod(0o600)
            preserved = working / "operator-data.txt"
            preserved.write_text("keep", encoding="utf-8")
            (content / "provider-new.txt").write_text("new", encoding="utf-8")
            with mock.patch.object(materialize_instance.os, "chown", return_value=None), \
                 mock.patch.object(materialize_instance.pwd, "getpwnam", return_value=agent_account), \
                 mock.patch.object(materialize_instance.grp, "getgrnam", return_value=agent_group):
                materialize_instance._prepare_private_state(spec, account, storage_root)
            self.assertEqual(preserved.read_text(encoding="utf-8"), "keep")
            self.assertEqual(stat.S_IMODE((working / "bedrock_server").stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(preserved.stat().st_mode), 0o600)
            self.assertFalse((working / "provider-new.txt").exists())
            outside = self.root / "outside-seed"
            outside.mkdir()
            escaped = {**spec, "seed_directories": [{"source": str(outside), "target": str(working)}]}
            with self.assertRaisesRegex(RuntimeError, "seed directory source escapes its allowed root"):
                with mock.patch.object(materialize_instance.os, "chown", return_value=None), \
                     mock.patch.object(materialize_instance.pwd, "getpwnam", return_value=agent_account), \
                     mock.patch.object(materialize_instance.grp, "getgrnam", return_value=agent_group):
                    materialize_instance._prepare_private_state(escaped, account, storage_root)
        finally:
            materialize_instance.STATE_DIR = original_state

    def test_private_seed_preserves_only_executable_semantics(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            executable = source / "server"
            regular = source / "config.txt"
            executable.write_text("binary", encoding="utf-8")
            regular.write_text("config", encoding="utf-8")
            executable.chmod(0o755)
            regular.chmod(0o644)
            account = type("Account", (), {"pw_uid": os.getuid(), "pw_gid": os.getgid()})()
            target = root / "target"
            materialize_instance._seed_directory(source, target, account)
            self.assertEqual(target.stat().st_mode & 0o777, 0o700)
            self.assertEqual((target / "server").stat().st_mode & 0o777, 0o700)
            self.assertEqual((target / "config.txt").stat().st_mode & 0o777, 0o600)


    def test_private_seed_overlay_repairs_missing_provider_files_without_removing_instance_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            target.mkdir()
            (source / "server.jar").write_bytes(b"provider-v1")
            (source / "libraries").mkdir()
            (source / "libraries" / "runtime.jar").write_bytes(b"library-v1")
            (target / "META-INF").mkdir()
            (target / "META-INF" / "MANIFEST.MF").write_text("stale extracted jar", encoding="utf-8")
            (target / "world").mkdir()
            (target / "world" / "level.dat").write_bytes(b"customer-world")
            account = type("Account", (), {"pw_uid": os.getuid(), "pw_gid": os.getgid()})()

            materialize_instance._seed_directory(source, target, account, overlay=True)

            self.assertEqual((target / "server.jar").read_bytes(), b"provider-v1")
            self.assertEqual((target / "libraries" / "runtime.jar").read_bytes(), b"library-v1")
            self.assertEqual((target / "world" / "level.dat").read_bytes(), b"customer-world")
            self.assertTrue((target / "META-INF" / "MANIFEST.MF").is_file())

            (source / "server.jar").write_bytes(b"provider-v2")
            materialize_instance._seed_directory(source, target, account, overlay=True)
            self.assertEqual((target / "server.jar").read_bytes(), b"provider-v2")
            self.assertEqual((target / "world" / "level.dat").read_bytes(), b"customer-world")

    def test_agent_control_state_is_private_but_traversable_from_instance_root(self):
        storage_root = self.root / "instances-control"
        instance_root = storage_root / "instance-control"
        control_root = instance_root / ".dsm"
        control_root.mkdir(parents=True)
        manifest = control_root / "content-activation-files.json"
        manifest.write_text('{"kind":"CapivaraContentFileProjection","targets":[]}\n', encoding="utf-8")
        os.chmod(instance_root, 0o700)
        os.chmod(control_root, 0o755)
        os.chmod(manifest, 0o644)
        spec = {
            "instance_id": "instance-control",
            "instance_state_root": str(instance_root),
            "working_directory": str(instance_root / "runtime"),
            "seed_files": [], "seed_directories": [], "bind_paths": [], "writable_directories": [],
        }
        runtime_account = type("Account", (), {"pw_uid": 1111, "pw_gid": 2222})()
        agent_account = type("Account", (), {"pw_uid": 3333, "pw_gid": 4444})()
        agent_group = type("Group", (), {"gr_gid": 4444})()
        with mock.patch.object(materialize_instance.os, "chown") as chown, \
             mock.patch.object(materialize_instance.pwd, "getpwnam", return_value=agent_account), \
             mock.patch.object(materialize_instance.grp, "getgrnam", return_value=agent_group):
            materialize_instance._prepare_private_state(spec, runtime_account, storage_root)
        self.assertEqual(stat.S_IMODE(instance_root.stat().st_mode), 0o710)
        self.assertEqual(stat.S_IMODE(control_root.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(manifest.stat().st_mode), 0o600)
        chown.assert_any_call(instance_root, runtime_account.pw_uid, agent_group.gr_gid)
        chown.assert_any_call(control_root, agent_account.pw_uid, agent_group.gr_gid)
        chown.assert_any_call(manifest, agent_account.pw_uid, agent_group.gr_gid)

    def test_hybrid_control_state_uses_configured_service_account(self):
        storage_root = self.root / "instances-hybrid-control"
        instance_root = storage_root / "instance-hybrid-control"
        control_root = instance_root / ".dsm"
        spec = {
            "instance_id": "instance-hybrid-control",
            "instance_state_root": str(instance_root),
            "working_directory": str(instance_root / "runtime"),
            "seed_files": [],
            "seed_directories": [],
            "bind_paths": [],
            "writable_directories": [],
        }
        runtime_account = type("Account", (), {"pw_uid": 1111, "pw_gid": 2222})()
        hybrid_control_account = type("Account", (), {"pw_uid": 5555, "pw_gid": 6666})()
        agent_group = type("Group", (), {"gr_gid": 4444})()
        old_control_user = os.environ.get("CAPIVARA_AGENT_RESULT_USER")
        os.environ["CAPIVARA_AGENT_RESULT_USER"] = "capivara"
        try:
            with mock.patch.object(materialize_instance.os, "chown") as chown, \
                 mock.patch.object(
                     materialize_instance.pwd,
                     "getpwnam",
                     side_effect=lambda name: hybrid_control_account
                     if name == "capivara"
                     else (_ for _ in ()).throw(KeyError(name)),
                 ) as getpwnam, \
                 mock.patch.object(materialize_instance.grp, "getgrnam", return_value=agent_group):
                materialize_instance._prepare_private_state(spec, runtime_account, storage_root)
        finally:
            if old_control_user is None:
                os.environ.pop("CAPIVARA_AGENT_RESULT_USER", None)
            else:
                os.environ["CAPIVARA_AGENT_RESULT_USER"] = old_control_user

        getpwnam.assert_called_once_with("capivara")
        self.assertEqual(stat.S_IMODE(control_root.stat().st_mode), 0o700)
        chown.assert_any_call(control_root, hybrid_control_account.pw_uid, agent_group.gr_gid)


    def test_remove_private_state_deletes_instance_owned_data_only(self):
        state = self.root / "hybrid-agent-state"
        storage_root = self.root / "hybrid-instance-storage"
        instance_root = storage_root / "instance-one"
        managed = state / "managed-content" / "instance-one"
        shared = state / "game-data" / "minecraft" / "youer" / "26.2" / "791"
        (instance_root / "runtime").mkdir(parents=True)
        managed.mkdir(parents=True)
        shared.mkdir(parents=True)
        (instance_root / "runtime" / "world.dat").write_text("instance", encoding="utf-8")
        (managed / "content.json").write_text("managed", encoding="utf-8")
        (shared / "server.jar").write_text("shared", encoding="utf-8")
        original_state = materialize_instance.STATE_DIR
        materialize_instance.STATE_DIR = state
        try:
            with mock.patch.object(materialize_instance, "_instance_storage_root", return_value=storage_root):
                result = materialize_instance._remove_instance_private_state(
                    {
                        "instance_id": "instance-one",
                        "instance_state_root": str(instance_root),
                    },
                    {"agent_id": "agent-one"},
                )
        finally:
            materialize_instance.STATE_DIR = original_state
        self.assertTrue(result["changed"])
        self.assertFalse(instance_root.exists())
        self.assertFalse(managed.exists())
        self.assertTrue((shared / "server.jar").is_file())
        self.assertTrue(result["shared_game_data_preserved"])


    def test_hybrid_runtime_boundary_is_repaired_for_runtime_group(self):
        state = self.root / "hybrid-agent-state"
        game_data = state / "game-data"
        working = game_data / "dayz" / "serverfiles"
        working.mkdir(parents=True)
        os.chmod(state, 0o700)
        os.chmod(game_data, 0o700)
        original_state = materialize_instance.STATE_DIR
        materialize_instance.STATE_DIR = state
        current_gid = state.stat().st_gid
        runtime_group = type("Group", (), {"gr_gid": current_gid})()
        try:
            with mock.patch.object(materialize_instance.grp, "getgrnam", return_value=runtime_group):
                materialize_instance._prepare_runtime_access(str(working), "capivara-instance")
                materialize_instance._validate_runtime_access(str(working), "capivara-instance")
        finally:
            materialize_instance.STATE_DIR = original_state
        self.assertEqual(state.stat().st_gid, current_gid)
        self.assertEqual(game_data.stat().st_gid, current_gid)
        self.assertEqual(stat.S_IMODE(state.stat().st_mode) & 0o010, 0o010)
        self.assertEqual(stat.S_IMODE(game_data.stat().st_mode) & 0o050, 0o050)
        self.assertEqual(stat.S_IMODE(state.stat().st_mode) & 0o007, 0)
        self.assertEqual(stat.S_IMODE(game_data.stat().st_mode) & 0o007, 0)


if __name__ == "__main__":
    unittest.main()
