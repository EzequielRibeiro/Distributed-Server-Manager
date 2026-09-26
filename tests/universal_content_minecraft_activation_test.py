#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _policy(*content_types: str) -> dict:
    directories = {"mod": "mods", "plugin": "plugins", "datapack": "world/datapacks"}
    return {
        "adapter": "minecraft-java",
        "types": {
            item: {"directory": directories[item], "extensions": [".jar"]}
            for item in content_types
        },
    }


class MinecraftActivationTest(unittest.TestCase):
    def _runtime_module(self, platform: str):
        return _load(
            ROOT / "agents" / platform / "runtime" / "content_activation_runtime.py",
            f"{platform}_minecraft_activation_runtime",
        )

    def _paper_round_trip(self, platform: str) -> None:
        module = self._runtime_module(platform)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime"
            state = root / "state"
            managed = runtime / "content" / "plugin-a"
            managed.mkdir(parents=True)
            state.mkdir()
            (managed / "Example.jar").write_bytes(b"plugin-v1")
            (runtime / "plugins").mkdir()
            (runtime / "plugins" / "manual.jar").write_bytes(b"customer-owned")
            spec = {
                "instance_id": "i1",
                "game_id": "minecraft",
                "environment_id": "minecraft.java.paper",
                "working_directory": str(runtime),
                "instance_state_root": str(state),
                "arguments": ["nogui"],
                "content_projection": _policy("plugin"),
            }
            snapshot = {
                "checksum": "paper-on",
                "entries": [{
                    "content_id": "plugin-a",
                    "game_id": "minecraft",
                    "content_type": "plugin",
                    "managed_path": str(managed),
                }],
            }
            projected = module.project_runtime_spec(spec, snapshot)
            self.assertEqual(projected["arguments"], ["nogui"])
            self.assertEqual(projected["content_file_projections"][0]["target_stem"], "plugins/capivara-plugin-a")
            written = module.materialize_content_activation(projected)
            self.assertEqual(written, ["plugins/capivara-plugin-a.jar"])
            self.assertEqual((runtime / "plugins" / "capivara-plugin-a.jar").read_bytes(), b"plugin-v1")
            self.assertEqual((runtime / "plugins" / "manual.jar").read_bytes(), b"customer-owned")

            disabled = module.project_runtime_spec(projected, {"checksum": "paper-off", "entries": []})
            self.assertEqual(module.materialize_content_activation(disabled), [])
            self.assertFalse((runtime / "plugins" / "capivara-plugin-a.jar").exists())
            self.assertTrue((runtime / "plugins" / "manual.jar").exists())
            self.assertEqual((managed / "Example.jar").read_bytes(), b"plugin-v1")

    def test_paper_plugin_enable_disable_linux(self):
        self._paper_round_trip("linux")

    def test_paper_plugin_enable_disable_windows(self):
        self._paper_round_trip("windows")

    def test_neoforge_rejects_plugin_and_accepts_mod(self):
        module = self._runtime_module("linux")
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "runtime"
            managed = runtime / "content" / "content-a"
            managed.mkdir(parents=True)
            (managed / "content.jar").write_bytes(b"jar")
            spec = {
                "instance_id": "i2", "game_id": "minecraft", "environment_id": "minecraft.java.neoforge",
                "working_directory": str(runtime), "instance_state_root": str(Path(tmp) / "state"),
                "arguments": [], "content_projection": _policy("mod"),
            }
            plugin = {"checksum": "bad", "entries": [{"content_id": "a", "game_id": "minecraft", "content_type": "plugin", "managed_path": str(managed)}]}
            with self.assertRaises(module.ContentRuntimeActivationError):
                module.project_runtime_spec(spec, plugin)
            mod = {"checksum": "ok", "entries": [{"content_id": "a", "game_id": "minecraft", "content_type": "mod", "managed_path": str(managed)}]}
            projected = module.project_runtime_spec(spec, mod)
            self.assertEqual(projected["content_file_projections"][0]["target_stem"], "mods/capivara-a")
            written = module.materialize_content_activation(projected)
            self.assertEqual(written, ["mods/capivara-a.jar"])
            self.assertEqual((runtime / "mods" / "capivara-a.jar").read_bytes(), b"jar")

    def test_hybrid_runtime_projects_mods_and_plugins(self):
        module = self._runtime_module("linux")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); runtime = root / "runtime"
            entries = []
            for content_id, content_type in (("mod-a", "mod"), ("plugin-a", "plugin")):
                managed = runtime / "content" / content_id
                managed.mkdir(parents=True, exist_ok=True)
                (managed / f"{content_id}.jar").write_bytes(content_id.encode())
                entries.append({"content_id": content_id, "game_id": "minecraft", "content_type": content_type, "managed_path": str(managed)})
            spec = {"instance_id": "i3", "game_id": "minecraft", "environment_id": "minecraft.java.arclight", "working_directory": str(runtime), "instance_state_root": str(root / "state"), "arguments": [], "content_projection": _policy("mod", "plugin")}
            projected = module.project_runtime_spec(spec, {"checksum": "hybrid", "entries": entries})
            self.assertEqual([item["target_stem"] for item in projected["content_file_projections"]], ["mods/capivara-mod-a", "plugins/capivara-plugin-a"])


    def test_provider_scoped_content_id_projects_to_portable_filename(self):
        for platform in ("linux", "windows"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as tmp:
                module = self._runtime_module(platform)
                root = Path(tmp)
                runtime = root / "runtime"
                state = root / "state"
                managed = runtime / "content" / "plugins" / "modrinth:Vebnzrzj"
                managed.mkdir(parents=True)
                state.mkdir()
                (managed / "LuckPerms-Bukkit-5.5.71.jar").write_bytes(b"luckperms")

                spec = {
                    "instance_id": "i-provider",
                    "game_id": "minecraft",
                    "environment_id": "minecraft.java.youer",
                    "working_directory": str(runtime),
                    "instance_state_root": str(state),
                    "arguments": [],
                    "content_projection": _policy("mod", "plugin"),
                }

                snapshot = {
                    "checksum": "provider-plugin",
                    "entries": [{
                        "content_id": "modrinth:Vebnzrzj",
                        "game_id": "minecraft",
                        "content_type": "plugin",
                        "managed_path": str(managed),
                    }],
                }

                projected = module.project_runtime_spec(spec, snapshot)

                self.assertEqual(
                    projected["content_file_projections"][0]["target_stem"],
                    "plugins/capivara-modrinth%3AVebnzrzj",
                )

                written = module.materialize_content_activation(projected)

                self.assertEqual(
                    written,
                    ["plugins/capivara-modrinth%3AVebnzrzj.jar"],
                )
                self.assertEqual(
                    (
                        runtime
                        / "plugins"
                        / "capivara-modrinth%3AVebnzrzj.jar"
                    ).read_bytes(),
                    b"luckperms",
                )

    def test_original_artifact_filename_is_preserved(self):
        for platform in ("linux", "windows"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as tmp:
                module = self._runtime_module(platform)
                root = Path(tmp); runtime = root / "runtime"; state = root / "state"
                managed = runtime / "content" / "mod-a"
                managed.mkdir(parents=True); state.mkdir()
                (managed / "payload.jar").write_bytes(b"mod")
                spec = {
                    "instance_id": "filename-1", "game_id": "minecraft",
                    "environment_id": "minecraft.java.youer",
                    "working_directory": str(runtime), "instance_state_root": str(state),
                    "arguments": [], "content_projection": _policy("mod"),
                }
                snapshot = {"checksum": "filename", "entries": [{
                    "content_id": "mb-deadbeef", "game_id": "minecraft",
                    "content_type": "mod", "managed_path": str(managed),
                    "artifact_filename": "YetAnotherConfigLib-3.9.6+26.2-neoforge.jar",
                }]}
                projected = module.project_runtime_spec(spec, snapshot)
                projection = projected["content_file_projections"][0]
                self.assertEqual(projection["target_name"], "mods/YetAnotherConfigLib-3.9.6+26.2-neoforge.jar")
                written = module.materialize_content_activation(projected)
                self.assertEqual(written, ["mods/YetAnotherConfigLib-3.9.6+26.2-neoforge.jar"])
                self.assertEqual((runtime / "mods" / "YetAnotherConfigLib-3.9.6+26.2-neoforge.jar").read_bytes(), b"mod")

    def test_refuses_unmanaged_target_collision(self):
        module = self._runtime_module("linux")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); runtime = root / "runtime"; state = root / "state"; managed = runtime / "content" / "a"
            managed.mkdir(parents=True); state.mkdir(); (managed / "a.jar").write_bytes(b"managed")
            target = runtime / "plugins" / "capivara-a.jar"; target.parent.mkdir(); target.write_bytes(b"unmanaged")
            spec = {"instance_id": "i4", "game_id": "minecraft", "environment_id": "minecraft.java.paper", "working_directory": str(runtime), "instance_state_root": str(state), "arguments": [], "content_projection": _policy("plugin")}
            snapshot = {"checksum": "collision", "entries": [{"content_id": "a", "game_id": "minecraft", "content_type": "plugin", "managed_path": str(managed)}]}
            projected = module.project_runtime_spec(spec, snapshot)
            with self.assertRaises(module.ContentRuntimeActivationError):
                module.materialize_content_activation(projected)
            self.assertEqual(target.read_bytes(), b"unmanaged")

    def test_projection_failure_restores_previous_managed_file(self):
        module = self._runtime_module("linux")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); runtime = root / "runtime"; state = root / "state"
            first = runtime / "content" / "a"; stale = runtime / "content" / "b"
            first.mkdir(parents=True); stale.mkdir(parents=True); state.mkdir()
            (first / "a.jar").write_bytes(b"v1"); (stale / "b.jar").write_bytes(b"b1")
            spec = {"instance_id": "i5", "game_id": "minecraft", "environment_id": "minecraft.java.paper", "working_directory": str(runtime), "instance_state_root": str(state), "arguments": [], "content_projection": _policy("plugin")}
            initial = {"checksum": "v1", "entries": [
                {"content_id": "a", "game_id": "minecraft", "content_type": "plugin", "managed_path": str(first)},
                {"content_id": "b", "game_id": "minecraft", "content_type": "plugin", "managed_path": str(stale)},
            ]}
            projected = module.project_runtime_spec(spec, initial); module.materialize_content_activation(projected)
            self.assertEqual((runtime / "plugins" / "capivara-a.jar").read_bytes(), b"v1")
            (first / "a.jar").write_bytes(b"v2")
            stale_target = runtime / "plugins" / "capivara-b.jar"
            stale_target.unlink(); stale_target.mkdir()
            update = {"checksum": "v2", "entries": [{"content_id": "a", "game_id": "minecraft", "content_type": "plugin", "managed_path": str(first)}]}
            with self.assertRaises(module.ContentRuntimeActivationError):
                module.materialize_content_activation(module.project_runtime_spec(projected, update))
            self.assertEqual((runtime / "plugins" / "capivara-a.jar").read_bytes(), b"v1")

    def _modpack_override_round_trip(self, platform: str) -> None:
        module = self._runtime_module(platform)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); runtime = root / "runtime"; state = root / "state"; managed = runtime / "content" / "modpacks" / "pack"
            (managed / "overrides" / "config").mkdir(parents=True); (managed / "server-overrides" / "config").mkdir(parents=True); state.mkdir()
            (managed / "overrides" / "config" / "pack.toml").write_text("layer=base\n", encoding="utf-8")
            (managed / "server-overrides" / "config" / "pack.toml").write_text("layer=server\n", encoding="utf-8")
            spec = {"instance_id":"bundle-1","game_id":"minecraft","environment_id":"minecraft.java.fabric","working_directory":str(runtime),"instance_state_root":str(state),"arguments":[],"content_projection":_policy("mod")}
            entry = {"content_id":"pack","game_id":"minecraft","content_type":"modpack","managed_path":str(managed),"activation":{"adapter":"minecraft-java","mode":"bundle-parent","identifier":"overrides,server-overrides"}}
            projected = module.project_runtime_spec(spec,{"checksum":"bundle-v1","entries":[entry]})
            self.assertEqual(projected["content_file_projections"],[])
            self.assertEqual(projected["content_bundle_overrides"][0]["roots"],["overrides","server-overrides"])
            self.assertEqual(module.materialize_content_activation(projected),["config/pack.toml"])
            target=runtime/"config"/"pack.toml";self.assertEqual(target.read_text(),"layer=server\n")
            (managed / "server-overrides" / "config" / "pack.toml").write_text("layer=server-v2\n",encoding="utf-8")
            updated=module.project_runtime_spec(projected,{"checksum":"bundle-v2","entries":[entry]});module.materialize_content_activation(updated);self.assertEqual(target.read_text(),"layer=server-v2\n")
            disabled=module.project_runtime_spec(updated,{"checksum":"bundle-off","entries":[]});self.assertEqual(module.materialize_content_activation(disabled),[]);self.assertFalse(target.exists())
            restored=module.project_runtime_spec(disabled,{"checksum":"bundle-on","entries":[entry]});module.materialize_content_activation(restored);self.assertEqual(target.read_text(),"layer=server-v2\n")
            target.write_text("customer-edit\n",encoding="utf-8");(managed / "server-overrides" / "config" / "pack.toml").write_text("layer=server-v3\n",encoding="utf-8")
            with self.assertRaises(module.ContentRuntimeActivationError):module.materialize_content_activation(module.project_runtime_spec(restored,{"checksum":"bundle-v3","entries":[entry]}))
            self.assertEqual(target.read_text(),"customer-edit\n")

    def test_modpack_overrides_linux(self):
        self._modpack_override_round_trip("linux")

    def test_modpack_overrides_windows(self):
        self._modpack_override_round_trip("windows")

    def test_modpack_override_cannot_bypass_managed_mods(self):
        module=self._runtime_module("linux")
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);runtime=root/"runtime";state=root/"state";managed=runtime/"content"/"modpacks"/"pack"; (managed/"overrides"/"mods").mkdir(parents=True);state.mkdir();(managed/"overrides"/"mods"/"evil.jar").write_bytes(b"jar")
            spec={"instance_id":"bundle-2","game_id":"minecraft","environment_id":"minecraft.java.fabric","working_directory":str(runtime),"instance_state_root":str(state),"arguments":[],"content_projection":_policy("mod")}
            entry={"content_id":"pack","game_id":"minecraft","content_type":"modpack","managed_path":str(managed),"activation":{"adapter":"minecraft-java","mode":"bundle-parent","identifier":"overrides"}}
            with self.assertRaises(module.ContentRuntimeActivationError):module.materialize_content_activation(module.project_runtime_spec(spec,{"checksum":"bad","entries":[entry]}))
            self.assertFalse((runtime/"mods"/"evil.jar").exists())

    def test_bedrock_does_not_consume_java_projection_manifests(self):
        for platform in ("linux", "windows"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as tmp:
                module = self._runtime_module(platform)
                root = Path(tmp); runtime = root / "runtime"; state = root / "state"
                runtime.mkdir(); (state / ".dsm").mkdir(parents=True)
                file_manifest = state / ".dsm" / "content-activation-files.json"
                override_manifest = state / ".dsm" / "content-activation-overrides.json"
                file_manifest.write_text(json.dumps({"schema_version": 1, "kind": "UnrelatedControlState", "targets": []}), encoding="utf-8")
                override_manifest.write_text(json.dumps({"schema_version": 1, "kind": "UnrelatedControlState", "targets": []}), encoding="utf-8")
                spec = {
                    "instance_id": "bedrock-one", "game_id": "minecraft",
                    "environment_id": "minecraft.bedrock.vanilla",
                    "working_directory": str(runtime), "instance_state_root": str(state),
                    "arguments": [],
                }
                projected = module.project_runtime_spec(spec, {"checksum": "empty", "entries": []})
                self.assertEqual(projected["content_file_projections"], [])
                self.assertEqual(projected["content_bundle_overrides"], [])
                self.assertEqual(module.materialize_content_activation(projected), [])
                self.assertEqual(json.loads(file_manifest.read_text())["kind"], "UnrelatedControlState")
                self.assertEqual(json.loads(override_manifest.read_text())["kind"], "UnrelatedControlState")

    def test_no_bundle_without_instance_state_root_is_noop(self):
        for platform in ("linux", "windows"):
            with self.subTest(platform=platform):
                module = self._runtime_module(platform)
                self.assertEqual(
                    module.materialize_minecraft_overrides({
                        "game_id": "minecraft",
                        "working_directory": "/tmp/nonexistent-runtime",
                        "content_bundle_overrides": [],
                    }),
                    [],
                )

    def test_catalog_policy_flows_to_linux_and_windows_profiles(self):
        for path in (ROOT / "database", ROOT / "dashboard"):
            value = str(path)
            if value not in sys.path:
                sys.path.insert(0, value)
        resolver = _load(ROOT / "dashboard" / "catalog_provisioning_resolver.py", "u5m_catalog_provisioning_resolver")
        selection = {"environment_id": "minecraft.java.paper"}
        _, config = resolver.resolve_catalog_provisioning(
            environment_id="minecraft.java.paper", selector="current", selection=selection, configuration={}, root=ROOT
        )
        managed = config["catalog_content_policy"]["managed"]
        self.assertEqual(set(managed["types"]), {"plugin"})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); install = root / "install"; install.mkdir(); state = root / "state"
            context = {
                "catalog_runtime_policy": {"runtime_id": "minecraft.java.paper", "engine": "java"},
                "catalog_content_policy": config["catalog_content_policy"],
                "install_path": str(install), "instance_state_root": str(state),
                "ports": {
                    "game": {"port": 25565, "protocol": "tcp"},
                    "rcon": {"port": 25575, "protocol": "tcp"},
                    "query": {"port": 25576, "protocol": "udp"},
                    "votifier": {"port": 25577, "protocol": "tcp"},
                },
            }
            instance = {"instance_id": "mc1", "agent_id": "agent-1", "environment_id": "minecraft.java.paper", "desired_state": "stopped"}
            from agents.linux.runtime.profiles.minecraft_java import MinecraftJavaRuntimeProfile as LinuxProfile
            from agents.windows.runtime.profiles.minecraft_java import MinecraftJavaRuntimeProfile as WindowsProfile
            self.assertEqual(LinuxProfile().build_runtime_spec(instance, context)["content_projection"], managed)
            self.assertEqual(WindowsProfile().build_runtime_spec(instance, context)["content_projection"], managed)

    def test_runtime_definition_capabilities_override_legacy_workspace_flags(self):
        for path in (ROOT / "database", ROOT / "dashboard"):
            value = str(path)
            if value not in sys.path:
                sys.path.insert(0, value)
        workspace = _load(ROOT / "dashboard" / "runtime_workspace_catalog.py", "u5m_runtime_workspace_catalog")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); game = root / "catalog" / "v2" / "games" / "minecraft"; runtimes = game / "runtimes"; runtimes.mkdir(parents=True)
            (game / "workspace-policy.json").write_text(json.dumps({
                "schema_version": 1, "kind": "GameWorkspacePolicy", "game": "minecraft", "products": {},
                "runtimes": {"minecraft.java.paper": {"mods": True, "plugins": False}},
            }), encoding="utf-8")
            (runtimes / "paper.json").write_text(json.dumps({
                "id": "minecraft.java.paper", "name": "Paper", "edition": "java",
                "content": {"managed": _policy("plugin")},
            }), encoding="utf-8")
            caps = workspace.runtime_workspace_capabilities(root, "minecraft", "minecraft.java.paper")
            self.assertFalse(caps["mods"]); self.assertTrue(caps["plugins"]); self.assertFalse(caps["datapacks"])

    def test_catalog_declares_expected_minecraft_capabilities(self):
        expected = {
            "java-paper.json": {"plugin"}, "java-purpur.json": {"plugin"}, "java-folia.json": {"plugin"},
            "java-fabric.json": {"mod"}, "java-forge.json": {"mod"}, "java-neoforge.json": {"mod"}, "java-quilt.json": {"mod"},
            "java-spongevanilla.json": {"plugin"}, "java-arclight.json": {"mod", "plugin"}, "java-youer.json": {"mod", "plugin"},
        }
        root = ROOT / "catalog" / "v2" / "games" / "minecraft" / "runtimes"
        for filename, kinds in expected.items():
            definition = json.loads((root / filename).read_text(encoding="utf-8"))
            managed = definition["content"]["managed"]
            self.assertEqual(managed["adapter"], "minecraft-java")
            self.assertEqual(set(managed["types"]), kinds)


if __name__ == "__main__":
    unittest.main()
