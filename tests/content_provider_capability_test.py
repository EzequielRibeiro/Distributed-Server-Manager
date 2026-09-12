#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_provider(relative_path: str, module_name: str):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ContentProviderCapabilityTest(unittest.TestCase):
    def _exercise(self, module):
        self.assertEqual(
            module.registered_providers(),
            ("github", "http", "http-archive", "local", "modrinth"),
        )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "game-data"
            source = root / "resolved" / "item"
            source.mkdir(parents=True)
            (source / "payload.bin").write_bytes(b"ok")
            stage = Path(td) / "stage"
            stage.mkdir()

            resolved = module.resolve_source(
                "steam-workshop",
                {"resolved_path": "resolved/item", "package_id": "221100:123"},
                stage,
                root,
            )
            self.assertEqual(resolved, source.resolve())

            with self.assertRaises(module.ContentProviderCapabilityError):
                module.resolve_source(
                    "steam-workshop",
                    {"package_id": "221100:123"},
                    stage,
                    root,
                )

            def fake_workshop(artifact, provider_stage, game_data_root):
                self.assertEqual(artifact["package_id"], "221100:123")
                self.assertEqual(provider_stage, stage)
                self.assertEqual(game_data_root, root)
                return source

            module.register_provider("steam-workshop", fake_workshop)
            self.assertEqual(
                module.resolve_source(
                    "steam-workshop",
                    {"package_id": "221100:123"},
                    stage,
                    root,
                ),
                source.resolve(),
            )

            outside = Path(td) / "outside"
            outside.mkdir()
            with self.assertRaises(ValueError):
                module.resolve_source(
                    "local",
                    {"path": str(outside)},
                    stage,
                    root,
                )

    def test_linux_provider_boundary(self):
        self._exercise(load_provider(
            "agents/linux/runtime/content_provider.py", "linux_content_provider_test"
        ))

    def test_windows_provider_boundary(self):
        self._exercise(load_provider(
            "agents/windows/runtime/content_provider.py", "windows_content_provider_test"
        ))

    def test_provider_modules_remain_game_neutral(self):
        for relative in (
            "agents/linux/runtime/content_provider.py",
            "agents/windows/runtime/content_provider.py",
        ):
            text = (ROOT / relative).read_text(encoding="utf-8").lower()
            for game in ("dayz", "project-zomboid", "minecraft", "ark", "rust", "valheim"):
                self.assertNotIn(game, text)


if __name__ == "__main__":
    unittest.main()
