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


def _published_runtime_providers() -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted((CATALOG / "games").glob("*/runtimes/*.json")):
        payload = _load_json(path)
        if payload.get("kind") != "RuntimeDefinition":
            continue
        provider = str((payload.get("artifact") or {}).get("provider") or "").strip()
        result[path.relative_to(ROOT).as_posix()] = provider
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

    def test_linux_and_windows_agents_implement_canonical_executable_set(self):
        linux = _agent_install_providers(LINUX_EXECUTOR)
        windows = _agent_install_providers(WINDOWS_EXECUTOR)
        self.assertEqual(linux, self.executable)
        self.assertEqual(windows, self.executable)
        self.assertEqual(linux, windows)

    def test_every_published_runtime_is_executable_by_both_agents(self):
        published = _published_runtime_providers()
        self.assertTrue(published, "catalog contains no published RuntimeDefinition entries")
        unsupported = {
            path: provider
            for path, provider in published.items()
            if not provider or provider not in self.executable
        }
        self.assertEqual(
            unsupported,
            {},
            "published runtimes must not use reserved/unimplemented artifact providers",
        )


if __name__ == "__main__":
    unittest.main()
