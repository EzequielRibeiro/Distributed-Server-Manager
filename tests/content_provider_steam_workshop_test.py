#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_workshop(relative_path: str, module_name: str, executable: Path):
    registered = {}
    provider_stub = types.ModuleType("content_provider")

    def register_provider(name, resolver, **kwargs):
        registered[name] = resolver

    provider_stub.register_provider = register_provider
    game_data_stub = types.ModuleType("game_data_executor")
    game_data_stub._steamcmd = lambda: str(executable)
    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    with patch.dict(sys.modules, {
        "content_provider": provider_stub,
        "game_data_executor": game_data_stub,
    }):
        spec.loader.exec_module(module)
    return module, registered


class SteamWorkshopCapabilityTest(unittest.TestCase):
    def _exercise(self, relative_path: str, module_name: str):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            executable = root / ("steamcmd.exe" if "windows" in relative_path else "steamcmd.sh")
            executable.write_text("stub", encoding="utf-8")
            module, registered = load_workshop(relative_path, module_name, executable)
            self.assertIn("steam-workshop", registered)
            self.assertIn("steam", registered)
            self.assertIs(registered["steam-workshop"], registered["steam"])

            game_data = root / "game-data"
            cache = executable.parent / "steamapps" / "workshop" / "content" / "221100" / "123456"
            cache.mkdir(parents=True)
            (cache / "payload.bin").write_bytes(b"workshop")

            completed = types.SimpleNamespace(returncode=0, stdout="Success")
            with patch.object(module.subprocess, "run", return_value=completed) as run:
                resolved = module.resolve_steam_workshop(
                    {"package_id": "221100:123456"}, root / "stage", game_data
                )
            self.assertEqual(resolved, cache.resolve())
            argv = run.call_args.args[0]
            self.assertEqual(argv[0], str(executable))
            self.assertIn("+workshop_download_item", argv)
            self.assertEqual(argv[argv.index("+workshop_download_item") + 1:argv.index("+workshop_download_item") + 3], ["221100", "123456"])
            self.assertNotIn("shell", run.call_args.kwargs)
            self.assertEqual(run.call_args.kwargs.get("stdin"), module.subprocess.DEVNULL)

            with self.assertRaises(ValueError):
                module.resolve_steam_workshop(
                    {"package_id": "221100;rm:123"}, root / "stage", game_data
                )

    def test_linux_workshop_capability(self):
        self._exercise(
            "agents/linux/runtime/content_provider_steam_workshop.py",
            "linux_content_provider_steam_workshop_test",
        )

    def test_windows_workshop_capability(self):
        self._exercise(
            "agents/windows/runtime/content_provider_steam_workshop.py",
            "windows_content_provider_steam_workshop_test",
        )

    def test_capability_contract_is_command_free_and_game_neutral(self):
        for relative in (
            "agents/linux/runtime/content_provider_steam_workshop.py",
            "agents/windows/runtime/content_provider_steam_workshop.py",
        ):
            text = (ROOT / relative).read_text(encoding="utf-8").lower()
            self.assertNotIn("shell=true", text)
            self.assertNotIn("os.system", text)
            self.assertNotIn("eval(", text)
            for game in ("dayz", "project-zomboid", "minecraft", "ark", "rust", "valheim"):
                self.assertNotIn(game, text)


if __name__ == "__main__":
    unittest.main()
