#!/usr/bin/env python3
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "database"))
SPEC = importlib.util.spec_from_file_location("registry", ROOT / "database" / "registry.py")
REGISTRY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REGISTRY)


class RegistryTest(unittest.TestCase):
    def repository(self, root: Path):
        return REGISTRY._repository(root / "data" / "capivara.db")

    def test_controller_profile_bootstrap_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self.repository(root)
            first = REGISTRY.installation_profile_identity(
                repository,
                profile="controller",
                hostname="controller-test",
            )
            second = REGISTRY.installation_profile_identity(
                repository,
                profile="controller",
                hostname="controller-test",
            )
            self.assertEqual(first["controller_id"], "controller-controller-test")
            self.assertEqual(first["controller_id"], second["controller_id"])
            self.assertFalse(first["placement_ready"])

    def test_standalone_agent_profile_waits_for_pairing(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = self.repository(Path(temporary))
            result = REGISTRY.installation_profile_identity(
                repository,
                profile="agent",
                hostname="agent-test",
            )
            self.assertEqual(result["agent_id"], "agent-agent-test")
            self.assertTrue(result["awaiting_pairing"])
            self.assertFalse(result["registered_with_controller"])
            self.assertFalse(result["placement_ready"])

    def test_hybrid_profile_bootstrap_is_placement_ready(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = self.repository(Path(temporary))
            result = REGISTRY.installation_profile_identity(
                repository,
                profile="hybrid",
                hostname="hybrid-test",
            )
            self.assertEqual(result["controller_id"], "controller-hybrid-test")
            self.assertEqual(result["agent_id"], "agent-hybrid-test")
            self.assertEqual(result["topology_state"], "ready")
            self.assertTrue(result["placement_ready"])

    def test_profile_rejects_unknown_role(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = self.repository(Path(temporary))
            with self.assertRaisesRegex(ValueError, "invalid installation profile"):
                REGISTRY.installation_profile_identity(
                    repository,
                    profile="unknown",
                    hostname="node-test",
                )

    def test_purge_orphan_rejects_unsafe_identifier(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "invalid instance identifier"):
                REGISTRY.purge_orphan_instance(
                    root,
                    root / "data" / "capivara.db",
                    "../unsafe",
                )

    def test_purge_orphan_rejects_missing_registry_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self.repository(root)
            repository.initialize()
            with self.assertRaisesRegex(ValueError, "instance is not registered"):
                REGISTRY.purge_orphan_instance(
                    root,
                    root / "data" / "capivara.db",
                    "missing-instance",
                )


if __name__ == "__main__":
    unittest.main()
