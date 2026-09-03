#!/usr/bin/env python3
from __future__ import annotations
import json
import unittest
from pathlib import Path

from core.installation_strategy import strategy_from_runtime_contract
from core.managed_configuration import resolve_managed_configuration
from core.runtime_engine_contract import canonical_from_runtime_v2, supports_agent
from core.runtime_readiness import evaluate_runtime_readiness

ROOT = Path(__file__).resolve().parents[1]


def load_runtime(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


class PostP0ArchitectureCompletionTest(unittest.TestCase):
    def test_managed_configuration_uses_canonical_precedence(self):
        resolved = resolve_managed_configuration(
            system={"network": {"port": 2302}},
            contract={"network": {"port": 2402, "query": 27016}, "slots": 40},
            customer={"network": {"port": 2502}, "slots": 60, "name": "Customer"},
        )
        self.assertEqual(resolved["effective"]["network"]["port"], 2302)
        self.assertEqual(resolved["effective"]["network"]["query"], 27016)
        self.assertEqual(resolved["effective"]["slots"], 40)
        self.assertEqual(resolved["effective"]["name"], "Customer")
        self.assertEqual(resolved["provenance"]["network"]["port"], "SYSTEM")

    def test_generic_readiness_states(self):
        self.assertEqual(evaluate_runtime_readiness({"process": True, "network": True})["state"], "ready")
        self.assertEqual(evaluate_runtime_readiness({"process": True, "network": True, "query": False})["state"], "degraded")
        self.assertEqual(evaluate_runtime_readiness({"process": False, "network": True})["state"], "unready")
        self.assertEqual(evaluate_runtime_readiness({"process": True})["state"], "unknown")

    def test_generic_multigame_contract_e2e_native_and_java(self):
        cases = [
            ("catalog/v2/games/dayz/runtimes/stable.json", "windows", "x86_64", "native"),
            ("catalog/v2/games/minecraft/runtimes/java-forge.json", "linux", "x86_64", "java"),
        ]
        games = set()
        for path, os_name, arch, engine in cases:
            runtime = load_runtime(path)
            contract = canonical_from_runtime_v2(runtime)
            strategy = strategy_from_runtime_contract(contract)
            games.add(contract["runtime"]["game"])
            self.assertEqual(contract["engine"]["kind"], engine)
            self.assertTrue(supports_agent(contract, os_name=os_name, architecture=arch))
            self.assertEqual(strategy["runtime_id"], contract["runtime"]["id"])
            self.assertFalse(strategy["layout"]["working_dir"].startswith(("/", "\\")))
        self.assertGreaterEqual(len(games), 2)

    def test_forge_is_generic_java_runtime_on_supported_provider(self):
        runtime = load_runtime("catalog/v2/games/minecraft/runtimes/java-forge.json")
        self.assertEqual(runtime["id"], "minecraft.java.forge")
        self.assertEqual(runtime["process"]["engine"], "java")
        self.assertEqual(runtime["artifact"]["provider"], "http")
        self.assertEqual(runtime["version"]["resolver"], "forge_maven")
        self.assertNotIn("forge", (ROOT / "core/runtime_engine_contract.py").read_text(encoding="utf-8").lower())


if __name__ == "__main__":
    unittest.main()
