#!/usr/bin/env python3

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "database"))

from backend import DatabaseConfig
from backend_factory import create_backend
from registry_repository import RegistryRepository


class RegistryRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        backend = create_backend(DatabaseConfig(
            driver="sqlite", database=str(Path(self.temp.name) / "capivara.db")
        ))
        self.repository = RegistryRepository(backend)

    def tearDown(self):
        self.repository.close()
        self.temp.cleanup()

    def test_aurora_is_idempotent(self):
        arguments = {
            "password_hash": "hash", "manifest_path": "/tmp/manifest.json",
            "metadata_json": '{"schema_version":1}',
        }
        self.repository.create_aurora(**arguments)
        self.repository.create_aurora(**arguments)
        instance = self.repository.get_instance("cliente-demo")
        self.assertEqual(instance["node_id"], "DemoNode")

    def test_delete_instance(self):
        self.repository.create_aurora(
            password_hash="hash", manifest_path="manifest",
            metadata_json="{}",
        )
        self.repository.delete_instance("cliente-demo")
        self.assertIsNone(self.repository.get_instance("cliente-demo"))


if __name__ == "__main__":
    unittest.main()
