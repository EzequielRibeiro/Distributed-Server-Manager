#!/usr/bin/env python3
from __future__ import annotations

import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ID = "mindustry.github"


def load_registry(platform: str):
    runtime = ROOT / "agents" / platform / "runtime"
    for module_name in list(sys.modules):
        if module_name == "profiles" or module_name.startswith("profiles."):
            del sys.modules[module_name]
    sys.path.insert(0, str(runtime))
    try:
        return importlib.import_module("profiles.registry")
    finally:
        sys.path.remove(str(runtime))


def context(install: Path, state: Path, tcp: int = 6567, udp: int = 6567) -> dict:
    return {
        "install_path": str(install),
        "content_root": str(install),
        "instance_state_root": str(state),
        "ports": {
            "game_tcp": {"port": tcp, "protocol": "tcp"},
            "game_udp": {"port": udp, "protocol": "udp"},
        },
        "catalog_runtime_policy": {"runtime_id": RUNTIME_ID, "engine": "java"},
        "environment": {},
    }


class MindustryRuntimeTest(unittest.TestCase):
    def test_runtime_is_published_not_deferred(self):
        active = ROOT / "catalog" / "v2" / "games" / "mindustry" / "runtimes" / "github.json"
        deferred = ROOT / "catalog" / "v2" / "games" / "mindustry" / "deferred" / "github.json"
        self.assertTrue(active.is_file())
        self.assertFalse(deferred.exists())
        definition = json.loads(active.read_text(encoding="utf-8"))
        self.assertEqual(definition["id"], RUNTIME_ID)
        self.assertEqual(definition["process"]["engine"], "java")
        self.assertEqual(definition["process"]["executable"], "@java")
        self.assertEqual(definition["requirements"]["os"], ["linux", "windows"])
        ports = definition["network"]["ports"]
        self.assertEqual({(p["name"], p["protocol"], p["offset"]) for p in ports}, {
            ("game_tcp", "tcp", 0),
            ("game_udp", "udp", 0),
        })

    def test_profiles_are_registered_on_linux_and_windows(self):
        for platform in ("linux", "windows"):
            registry = load_registry(platform)
            self.assertIn(RUNTIME_ID, registry.supported_profiles())
            profile = registry.resolve_profile({"game_id": "mindustry", "environment_id": RUNTIME_ID})
            self.assertEqual(profile.profile_version, 1)

    def test_two_instances_share_jar_but_keep_runtime_state_private(self):
        for platform in ("linux", "windows"):
            registry = load_registry(platform)
            with tempfile.TemporaryDirectory() as td:
                root = Path(td).resolve()
                install = root / "shared" / "mindustry" / "serverfiles"
                install.mkdir(parents=True)
                (install / "server-release.jar").write_bytes(b"jar")
                state_a = root / "pool" / "mindustry-a"
                state_b = root / "pool" / "mindustry-b"
                profile = registry.resolve_profile({"game_id": "mindustry", "environment_id": RUNTIME_ID})
                base = {"agent_id": "agent-1", "game_id": "mindustry", "environment_id": RUNTIME_ID}
                a = profile.build_runtime_spec({**base, "instance_id": "mindustry-a"}, context(install, state_a))
                b = profile.build_runtime_spec({**base, "instance_id": "mindustry-b"}, context(install, state_b))
                jar = str(install / "server-release.jar")
                self.assertEqual(a["arguments"][:2], ["-jar", jar])
                self.assertEqual(b["arguments"][:2], ["-jar", jar])
                self.assertEqual(a["arguments"][2], "config port 6567,host")
                self.assertNotEqual(a["working_directory"], b["working_directory"])
                self.assertTrue(a["working_directory"].startswith(str(state_a)))
                self.assertTrue(b["working_directory"].startswith(str(state_b)))
                self.assertEqual(a["seed_directories"], [])
                self.assertEqual(b["seed_directories"], [])

    def test_tcp_and_udp_must_share_the_same_number(self):
        for platform in ("linux", "windows"):
            registry = load_registry(platform)
            with tempfile.TemporaryDirectory() as td:
                root = Path(td).resolve()
                install = root / "shared"
                install.mkdir()
                profile = registry.resolve_profile({"game_id": "mindustry", "environment_id": RUNTIME_ID})
                with self.assertRaises(Exception):
                    profile.build_runtime_spec(
                        {"agent_id": "agent-1", "instance_id": "mindustry-a", "game_id": "mindustry", "environment_id": RUNTIME_ID},
                        context(install, root / "state", tcp=6567, udp=6568),
                    )


if __name__ == "__main__":
    unittest.main()
