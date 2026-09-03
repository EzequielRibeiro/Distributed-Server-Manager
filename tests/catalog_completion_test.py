#!/usr/bin/env python3
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog/v2"
GAMES = CATALOG / "games"
MATRIX = CATALOG / "support-matrix.json"
PROVIDERS = CATALOG / "providers/catalog-providers.json"
RESOLVERS = ROOT / "installer/version_resolvers"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def published():
    rows = []
    for path in sorted(GAMES.glob("*/runtimes/*.json")):
        payload = load(path)
        if payload.get("kind") == "RuntimeDefinition":
            rows.append((path, payload))
    return rows


class CatalogCompletionTest(unittest.TestCase):
    def setUp(self):
        self.matrix = load(MATRIX)
        self.provider_registry = load(PROVIDERS)
        self.rows = published()
        self.by_id = {payload["id"]: (path, payload) for path, payload in self.rows}

    def test_support_matrix_exactly_matches_published_runtime_set(self):
        matrix_rows = self.matrix["published_runtimes"]
        matrix_ids = [row["id"] for row in matrix_rows]
        published_ids = [payload["id"] for _, payload in self.rows]
        self.assertEqual(len(matrix_ids), len(set(matrix_ids)), "support matrix contains duplicate runtime IDs")
        self.assertEqual(len(published_ids), len(set(published_ids)), "catalog contains duplicate runtime IDs")
        self.assertEqual(set(matrix_ids), set(published_ids))
        self.assertTrue(all(row.get("status") == "supported" for row in matrix_rows))

    def test_runtime_contract_is_complete_and_matches_matrix(self):
        matrix = {row["id"]: row for row in self.matrix["published_runtimes"]}
        executable = set(self.provider_registry["agent_executable_artifact_providers"])
        for runtime_id, (path, payload) in self.by_id.items():
            with self.subTest(runtime=runtime_id):
                game = path.parts[path.parts.index("games") + 1]
                self.assertEqual(payload.get("schema_version"), 2)
                self.assertEqual(payload.get("kind"), "RuntimeDefinition")
                self.assertEqual(payload.get("game"), game)
                self.assertTrue(str(payload.get("edition") or "").strip())
                self.assertTrue(str(payload.get("variant") or "").strip())
                process = payload.get("process") or {}
                self.assertIn(process.get("engine"), {"java", "native"})
                self.assertTrue(str(process.get("executable") or "").strip())
                requirements = payload.get("requirements") or {}
                os_values = requirements.get("os") or []
                architectures = requirements.get("architectures") or []
                self.assertTrue(os_values)
                self.assertTrue(architectures)
                self.assertTrue(set(os_values) <= {"linux", "windows"})
                if process.get("engine") == "java":
                    java = requirements.get("java") or {}
                    self.assertIsInstance(java.get("min"), int)
                    self.assertIsInstance(java.get("max"), int)
                    self.assertLessEqual(java["min"], java["max"])
                artifact = payload.get("artifact") or {}
                provider = str(artifact.get("provider") or "")
                self.assertIn(provider, executable, f"{runtime_id} uses a reserved/non-executable provider")
                if provider == "steam":
                    self.assertTrue(str(artifact.get("package_id") or "").isdigit())
                if provider == "github":
                    self.assertIn("/", str(artifact.get("repository") or ""))
                version = payload.get("version") or {}
                strategy = version.get("strategy")
                self.assertIn(strategy, {"static", "dynamic"})
                resolver = version.get("resolver")
                if strategy == "dynamic":
                    self.assertTrue(str(resolver or "").strip())
                    self.assertTrue((RESOLVERS / f"{resolver}.sh").is_file(), f"missing resolver for {runtime_id}")
                installation = payload.get("installation") or {}
                self.assertTrue(str(installation.get("directory") or "").startswith("/"))
                expected = matrix[runtime_id]
                self.assertEqual(expected["game"], game)
                self.assertEqual(expected["engine"], process["engine"])
                self.assertEqual(expected["provider"], provider)
                self.assertEqual(expected["version_strategy"], strategy)
                self.assertEqual(expected.get("resolver"), resolver)
                self.assertEqual(expected["os"], os_values)

    def test_network_contract_is_deterministic(self):
        allowed_apply = {"argument", "property", "derived"}
        for runtime_id, (_, payload) in self.by_id.items():
            network = payload.get("network")
            if not network:
                continue
            with self.subTest(runtime=runtime_id):
                self.assertEqual(network.get("allocation"), "block")
                block_size = network.get("block_size")
                self.assertIsInstance(block_size, int)
                self.assertGreater(block_size, 0)
                ports = network.get("ports") or []
                names = [item.get("name") for item in ports]
                protocol_offsets = [(item.get("protocol"), item.get("offset")) for item in ports]
                self.assertEqual(len(names), len(set(names)))
                self.assertEqual(len(protocol_offsets), len(set(protocol_offsets)), "duplicate protocol/offset binding")
                for item in ports:
                    self.assertIn(item.get("protocol"), {"tcp", "udp"})
                    self.assertGreaterEqual(item.get("offset"), 0)
                    self.assertLess(item.get("offset"), block_size)
                for operation in network.get("apply") or []:
                    self.assertIn(operation.get("kind"), allowed_apply)
                    if operation.get("kind") == "derived":
                        self.assertIn(operation.get("port"), names)
                        self.assertIn(operation.get("from"), names)

    def test_deferred_runtime_is_not_customer_publishable(self):
        published_ids = set(self.by_id)
        for row in self.matrix.get("deferred_runtimes") or []:
            runtime_id = row["id"]
            self.assertNotIn(runtime_id, published_ids)
            self.assertEqual(row.get("status"), "deferred")
            self.assertTrue(row.get("reason"))
            deferred_files = list((GAMES / row["game"] / "deferred").glob("*.json"))
            self.assertTrue(any(load(path).get("id") == runtime_id for path in deferred_files))

    def test_mohist_and_starlight_are_not_published_as_runtimes(self):
        lowered = "\n".join(self.by_id).lower()
        self.assertNotIn("mohist", lowered)
        self.assertNotIn("starlight", lowered)
        explicit = {row["id"] for row in self.matrix.get("explicitly_not_published_as_runtimes") or []}
        self.assertEqual(explicit, {"mohist", "starlight"})


if __name__ == "__main__":
    unittest.main()
