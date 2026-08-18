#!/usr/bin/env python3

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dashboard"))


from catalog_configuration import CatalogConfigurationService


class CatalogConfigurationTest(unittest.TestCase):
    def test_json_file_can_be_read_and_validated(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "catalog" / "v2" / "sample.json"
            path.parent.mkdir(parents=True)
            path.write_text(
                '{"enabled": true}\n',
                encoding="utf-8",
            )

            service = CatalogConfigurationService(root)
            result = service.read("v2/sample.json")

            self.assertIn("enabled", result["content"])

            with self.assertRaises(ValueError):
                service.write(
                    "v2/sample.json",
                    "{invalid",
                )

    def test_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            service = CatalogConfigurationService(Path(temp))

            with self.assertRaises(ValueError):
                service.read("../outside.json")


if __name__ == "__main__":
    unittest.main()
