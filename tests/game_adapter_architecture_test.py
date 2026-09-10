#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GAMES = ROOT / "games"
FIXTURES = ROOT / "tests" / "fixtures" / "game-adapters"

PROVIDER_FIXTURES = {
    "custom-provider-test",
    "github-provider-test",
    "http-fail-test",
    "http-provider-test",
    "local-provider-test",
}

PRODUCTION_ADAPTERS = {
    "arma3",
    "dayz",
    "luanti",
    "mindustry",
    "minecraft",
    "minecraft-java",
    "rust",
}


class GameAdapterArchitectureTest(unittest.TestCase):
    def test_provider_fixtures_are_not_production_game_adapters(self):
        root_names = {path.name for path in GAMES.iterdir() if path.is_dir()}
        self.assertFalse(root_names & PROVIDER_FIXTURES)
        for name in PROVIDER_FIXTURES:
            self.assertTrue((FIXTURES / name / "game.conf").is_file(), name)

    def test_known_shell_adapters_keep_runtime_contract(self):
        for name in PRODUCTION_ADAPTERS:
            adapter = GAMES / name
            self.assertTrue(adapter.is_dir(), name)
            self.assertTrue((adapter / "runtime.sh").is_file(), name)

    def test_documentation_declares_catalog_as_install_authority(self):
        text = (GAMES / "README.md").read_text(encoding="utf-8")
        self.assertIn("catalog/v2/games/<game>/runtimes/", text)
        self.assertIn("tests/fixtures/game-adapters/", text)
        self.assertNotIn("catalog/v2/runtimes/", text)


if __name__ == "__main__":
    unittest.main()
