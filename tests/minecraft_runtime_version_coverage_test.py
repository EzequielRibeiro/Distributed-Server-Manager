#!/usr/bin/env python3
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIMES = ROOT / "catalog" / "v2" / "games" / "minecraft" / "runtimes"

class MinecraftRuntimeVersionCoverageTest(unittest.TestCase):
    def test_all_java_runtimes_use_dynamic_version_discovery(self):
        static = []
        for path in sorted(RUNTIMES.glob("java-*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            if str((data.get("version") or {}).get("strategy") or "") != "dynamic":
                static.append(str(data.get("id") or path.name))
        self.assertEqual([], static, f"Minecraft Java runtimes must not be pinned to one static game version: {static}")

    def test_vanilla_uses_official_mojang_manifest_resolver(self):
        data = json.loads((RUNTIMES / "java-vanilla.json").read_text(encoding="utf-8"))
        version = data["version"]
        self.assertEqual("dynamic", version["strategy"])
        self.assertEqual("minecraft_java", version["resolver"])
        self.assertIn("piston-meta.mojang.com", version["config"]["manifest_url"])
        self.assertGreaterEqual(int(version["config"]["discovery_limit"]), 20)

    def test_youer_remains_explicitly_scoped_to_upstream_supported_version(self):
        data = json.loads((RUNTIMES / "java-youer.json").read_text(encoding="utf-8"))
        self.assertEqual(["1.21.1"], data["version"]["config"]["supported_versions"])

if __name__ == "__main__":
    unittest.main()
