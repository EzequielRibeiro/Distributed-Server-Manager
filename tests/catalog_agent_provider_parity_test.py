#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog/v2"
REGISTRY = CATALOG / "providers/catalog-providers.json"
SCHEMA = CATALOG / "schemas/runtime-definition.schema.json"
LINUX_EXECUTOR = ROOT / "agents/linux/runtime/game_data_executor.py"
WINDOWS_EXECUTOR = ROOT / "agents/windows/runtime/game_data_executor.py"


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _agent_install_providers(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    install = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_install"
    )
    providers: set[str] = set()
    for node in ast.walk(install):
        if not isinstance(node, ast.Compare) or len(node.ops) != 1 or len(node.comparators) != 1:
            continue
        if not isinstance(node.left, ast.Name) or node.left.id != "provider":
            continue
        op = node.ops[0]
        comparator = node.comparators[0]
        if isinstance(op, ast.Eq) and isinstance(comparator, ast.Constant) and isinstance(comparator.value, str):
            providers.add(comparator.value)
        elif isinstance(op, ast.In) and isinstance(comparator, (ast.Set, ast.Tuple, ast.List)):
            for element in comparator.elts:
                if isinstance(element, ast.Constant) and isinstance(element.value, str):
                    providers.add(element.value)
    return providers


def _published_runtime_contracts() -> dict[str, tuple[str, set[str]]]:
    result: dict[str, tuple[str, set[str]]] = {}
    for path in sorted((CATALOG / "games").glob("*/runtimes/*.json")):
        payload = _load_json(path)
        if payload.get("kind") != "RuntimeDefinition":
            continue
        provider = str((payload.get("artifact") or {}).get("provider") or "").strip()
        os_values = {
            str(value).strip().lower()
            for value in ((payload.get("requirements") or {}).get("os") or [])
            if str(value).strip()
        }
        result[path.relative_to(ROOT).as_posix()] = (provider, os_values)
    return result


class CatalogAgentProviderParityTest(unittest.TestCase):
    def setUp(self):
        self.registry = _load_json(REGISTRY)
        self.schema = _load_json(SCHEMA)
        self.universe = set(self.registry["artifact_providers"])
        self.executable = set(self.registry["agent_executable_artifact_providers"])
        self.reserved = set(self.registry["reserved_artifact_providers"])

    def test_registry_matches_runtime_schema_provider_universe(self):
        schema_providers = set(
            self.schema["properties"]["artifact"]["properties"]["provider"]["enum"]
        )
        self.assertEqual(schema_providers, self.universe)

    def test_executable_and_reserved_sets_partition_provider_universe(self):
        self.assertTrue(self.executable)
        self.assertFalse(self.executable & self.reserved)
        self.assertEqual(self.executable | self.reserved, self.universe)

    def test_agents_implement_executable_providers_required_by_their_platform(self):
        contracts = _published_runtime_contracts()
        linux_required = {
            provider for provider, os_values in contracts.values()
            if provider in self.executable and "linux" in os_values
        }
        windows_required = {
            provider for provider, os_values in contracts.values()
            if provider in self.executable and "windows" in os_values
        }
        linux = _agent_install_providers(LINUX_EXECUTOR)
        windows = _agent_install_providers(WINDOWS_EXECUTOR)
        self.assertTrue(linux_required <= linux)
        self.assertTrue(windows_required <= windows)
        self.assertFalse(linux - self.executable)
        self.assertFalse(windows - self.executable)

    def test_every_published_runtime_uses_an_executable_provider(self):
        published = _published_runtime_contracts()
        self.assertTrue(published, "catalog contains no published RuntimeDefinition entries")
        unsupported = {
            path: provider
            for path, (provider, _os_values) in published.items()
            if not provider or provider not in self.executable
        }
        self.assertEqual(
            unsupported,
            {},
            "published runtimes must not use reserved/unimplemented artifact providers",
        )


if __name__ == "__main__":
    unittest.main()
