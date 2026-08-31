#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class MinecraftInstallerRuntimeTest(unittest.TestCase):
    def test_catalog_prepare_carries_installer_contract_canonically(self):
        with tempfile.TemporaryDirectory() as td:
            catalog_root = Path(td) / "catalog" / "v2"
            runtime_dir = catalog_root / "games" / "fixture" / "runtimes"
            runtime_dir.mkdir(parents=True)
            runtime = {
                "schema_version": 2,
                "id": "fixture.java.installer",
                "game": "fixture",
                "edition": "java",
                "variant": "installer",
                "version": {"strategy": "static", "value": "1.0.0"},
                "artifact": {"provider": "http-archive", "asset": "installer.jar"},
                "installation": {
                    "directory": "/opt/dsm/game-data/fixture/installer",
                    "installer": {
                        "type": "java_jar",
                        "args": ["--installServer"],
                        "timeout_seconds": 600,
                        "expected_outputs": ["libraries"],
                    },
                },
                "process": {"engine": "java", "executable": "@java"},
            }
            (runtime_dir / "installer.json").write_text(json.dumps(runtime), encoding="utf-8")
            env = dict(os.environ)
            env["DSM_ROOT"] = str(ROOT)
            env["DSM_CATALOG_ROOT"] = str(catalog_root)
            completed = subprocess.run(
                [str(ROOT / "installer/catalog.sh"), "runtime", "prepare", "fixture.java.installer", "current", "--json"],
                cwd=str(ROOT),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            selection = json.loads(completed.stdout)
            self.assertEqual(selection["kind"], "RuntimeSelection")
            self.assertEqual(selection["runtime_definition"], "fixture.java.installer")
            self.assertEqual(selection["installer"], runtime["installation"]["installer"])

    def test_linux_java_installer_is_argv_only_and_normalizes_launch_args(self):
        module = load("linux_game_data_installer", ROOT / "agents/linux/runtime/game_data_installer.py")
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            (target / "forge-installer.jar").write_bytes(b"jar")
            args_file = target / "libraries/net/minecraftforge/forge/1.21.1-52.0.0/unix_args.txt"
            args_file.parent.mkdir(parents=True)
            args_file.write_text("--class-path libraries/example.jar", encoding="utf-8")
            (target / "user_jvm_args.txt").write_text("-Xmx2G", encoding="utf-8")
            selection = {
                "asset": {"name": "forge-installer.jar"},
                "installer": {
                    "type": "java_jar",
                    "args": ["--installServer"],
                    "timeout_seconds": 600,
                    "launch_args": {
                        "linux_glob": "libraries/net/minecraftforge/forge/*/unix_args.txt",
                        "windows_glob": "libraries/net/minecraftforge/forge/*/win_args.txt",
                        "output": "capivara-launch.args",
                    },
                    "expected_outputs": ["libraries", "user_jvm_args.txt", "capivara-launch.args"],
                },
            }
            completed = type("Completed", (), {"returncode": 0, "stdout": "ok\n"})()
            with patch.object(module.shutil, "which", return_value="/usr/bin/java"), patch.object(module.subprocess, "run", return_value=completed) as run:
                module.execute_installer(selection, target)
            argv = run.call_args.args[0]
            self.assertEqual(argv[:3], ["/usr/bin/java", "-jar", str(target / "forge-installer.jar")])
            self.assertEqual(argv[3:], ["--installServer"])
            self.assertNotIn("shell", run.call_args.kwargs)
            self.assertEqual((target / "capivara-launch.args").read_text(encoding="utf-8"), args_file.read_text(encoding="utf-8"))

    def test_installer_rejects_shell_like_arguments_and_path_escape(self):
        module = load("linux_game_data_installer_invalid", ROOT / "agents/linux/runtime/game_data_installer.py")
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            (target / "installer.jar").write_bytes(b"jar")
            with patch.object(module.shutil, "which", return_value="/usr/bin/java"):
                with self.assertRaises(ValueError):
                    module.validate_installer({"asset": {"name": "installer.jar"}, "installer": {"type": "java_jar", "args": ["--installServer", ";rm"]}}, target)
                with self.assertRaises(ValueError):
                    module.validate_installer({"installer": {"type": "java_jar", "artifact": "../installer.jar", "args": ["--installServer"]}}, target)

    def test_windows_installer_contract_uses_win_args(self):
        module = load("windows_game_data_installer", ROOT / "agents/windows/runtime/game_data_installer.py")
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            (target / "neoforge-installer.jar").write_bytes(b"jar")
            args_file = target / "libraries/net/neoforged/neoforge/21.1.1/win_args.txt"
            args_file.parent.mkdir(parents=True)
            args_file.write_text("--module-path libraries", encoding="utf-8")
            (target / "user_jvm_args.txt").write_text("-Xmx2G", encoding="utf-8")
            selection = {
                "asset": {"name": "neoforge-installer.jar"},
                "installer": {
                    "type": "java_jar",
                    "args": ["--installServer"],
                    "launch_args": {
                        "linux_glob": "libraries/net/neoforged/neoforge/*/unix_args.txt",
                        "windows_glob": "libraries/net/neoforged/neoforge/*/win_args.txt",
                        "output": "capivara-launch.args",
                    },
                    "expected_outputs": ["libraries", "user_jvm_args.txt", "capivara-launch.args"],
                },
            }
            completed = type("Completed", (), {"returncode": 0, "stdout": ""})()
            with patch.object(module.shutil, "which", return_value="C:/Java/bin/java.exe"), patch.object(module.subprocess, "run", return_value=completed):
                module.execute_installer(selection, target)
            self.assertEqual((target / "capivara-launch.args").read_text(encoding="utf-8"), args_file.read_text(encoding="utf-8"))

    def test_catalog_contains_forge_and_neoforge_but_not_mohist(self):
        runtime_root = ROOT / "catalog/v2/games/minecraft/runtimes"
        runtimes = [json.loads(path.read_text(encoding="utf-8")) for path in runtime_root.glob("*.json")]
        ids = {item["id"] for item in runtimes}
        self.assertIn("minecraft.java.forge", ids)
        self.assertIn("minecraft.java.neoforge", ids)
        self.assertFalse(any("mohist" in str(item).lower() for item in runtimes))
        for runtime_id in ("minecraft.java.forge", "minecraft.java.neoforge"):
            runtime = next(item for item in runtimes if item["id"] == runtime_id)
            self.assertEqual(runtime["process"]["executable"], "@java")
            self.assertEqual(runtime["installation"]["installer"]["type"], "java_jar")
            self.assertEqual(runtime["installation"]["installer"]["args"], ["--installServer"])
            self.assertEqual(runtime["requirements"]["os"], ["linux", "windows"])

    def test_resolvers_use_official_maven_hosts_and_checksums(self):
        forge = (ROOT / "installer/version_resolvers/forge_maven.sh").read_text(encoding="utf-8")
        neo = (ROOT / "installer/version_resolvers/neoforge_maven.sh").read_text(encoding="utf-8")
        self.assertIn("https://maven.minecraftforge.net/net/minecraftforge/forge", forge)
        self.assertIn("https://maven.neoforged.net/releases/net/neoforged/neoforge", neo)
        self.assertIn(".sha256", forge)
        self.assertIn(".sha256", neo)


if __name__ == "__main__":
    unittest.main()
