#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JAVA_IDS = (
    "minecraft.java.arclight",
    "minecraft.java.fabric",
    "minecraft.java.folia",
    "minecraft.java.forge",
    "minecraft.java.neoforge",
    "minecraft.java.paper",
    "minecraft.java.purpur",
    "minecraft.java.quilt",
    "minecraft.java.spongevanilla",
    "minecraft.java.vanilla",
    "minecraft.java.youer",
)


def load_registry(platform: str):
    runtime = ROOT / "agents" / platform / "runtime"
    for name in list(sys.modules):
        if name == "profiles" or name.startswith("profiles."):
            del sys.modules[name]
    sys.path.insert(0, str(runtime))
    try:
        path = runtime / "profiles" / "registry.py"
        spec = importlib.util.spec_from_file_location(f"minecraft_registry_{platform}", path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(runtime))


def context(install: Path, state: Path, runtime_id: str) -> dict:
    return {
        "install_path": str(install),
        "content_root": str(install),
        "instance_state_root": str(state),
        "ports": {"game": {"port": 25565, "protocol": "tcp"}},
        "catalog_runtime_policy": {"runtime_id": runtime_id, "engine": "java"},
        "environment": {},
    }


class MinecraftJavaInstanceIsolationTest(unittest.TestCase):
    def test_all_java_environment_ids_are_registered_on_linux_and_windows(self):
        for platform in ("linux", "windows"):
            registry = load_registry(platform)
            supported = set(registry.supported_profiles())
            self.assertTrue(set(JAVA_IDS).issubset(supported), (platform, supported))
            for runtime_id in JAVA_IDS:
                profile = registry.resolve_profile({"game_id": "minecraft", "environment_id": runtime_id})
                self.assertEqual(profile.profile_version, 1)

    def test_two_instances_share_provider_seed_but_not_working_state(self):
        for platform in ("linux", "windows"):
            registry = load_registry(platform)
            with tempfile.TemporaryDirectory() as td:
                root = Path(td).resolve()
                install = root / "shared" / "minecraft" / "serverfiles"
                install.mkdir(parents=True)
                state_a = root / "pool" / "mc-a"
                state_b = root / "pool" / "mc-b"
                runtime_id = "minecraft.java.paper"
                profile = registry.resolve_profile({"game_id": "minecraft", "environment_id": runtime_id})
                base = {"agent_id": "agent-1", "game_id": "minecraft", "environment_id": runtime_id}
                a = profile.build_runtime_spec({**base, "instance_id": "mc-a"}, context(install, state_a, runtime_id))
                b = profile.build_runtime_spec({**base, "instance_id": "mc-b"}, context(install, state_b, runtime_id))
                self.assertEqual(a["seed_directories"][0]["source"], str(install))
                self.assertEqual(b["seed_directories"][0]["source"], str(install))
                self.assertNotEqual(a["working_directory"], b["working_directory"])
                self.assertNotEqual(a["seed_directories"][0]["target"], b["seed_directories"][0]["target"])
                self.assertTrue(a["working_directory"].startswith(str(state_a)))
                self.assertTrue(b["working_directory"].startswith(str(state_b)))

    def test_bedrock_or_generic_minecraft_never_falls_into_java_profile(self):
        for platform in ("linux", "windows"):
            registry = load_registry(platform)
            for environment_id in ("minecraft.bedrock.vanilla", "minecraft"):
                with self.assertRaises(Exception):
                    registry.resolve_profile({"game_id": "minecraft", "environment_id": environment_id})

    def test_catalog_policy_runtime_id_must_match(self):
        for platform in ("linux", "windows"):
            registry = load_registry(platform)
            with tempfile.TemporaryDirectory() as td:
                root = Path(td).resolve()
                install = root / "shared"
                install.mkdir()
                runtime_id = "minecraft.java.paper"
                profile = registry.resolve_profile({"game_id": "minecraft", "environment_id": runtime_id})
                bad = context(install, root / "state", "minecraft.java.forge")
                with self.assertRaises(Exception):
                    profile.build_runtime_spec(
                        {"agent_id": "agent-1", "instance_id": "mc-a", "game_id": "minecraft", "environment_id": runtime_id},
                        bad,
                    )


if __name__ == "__main__":
    unittest.main()
