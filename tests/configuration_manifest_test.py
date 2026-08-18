#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from core.configuration.manifest import (
    ConfigurationManifest,
    ConfigurationManifestError,
)


class ConfigurationManifestTest(unittest.TestCase):
    def test_declared_files_are_loaded(self):
        manifest = ConfigurationManifest.from_runtime_definition(
            {
                "configuration": {
                    "files": [
                        {
                            "id": "server",
                            "path": "serverDZ.cfg",
                            "category": "game",
                        }
                    ]
                }
            }
        )

        self.assertEqual(len(manifest.entries), 1)
        self.assertEqual(
            manifest.entries[0].path,
            "serverDZ.cfg",
        )

    def test_parent_traversal_is_rejected(self):
        with self.assertRaises(ConfigurationManifestError):
            ConfigurationManifest.from_runtime_definition(
                {
                    "configuration": {
                        "files": [
                            {
                                "id": "bad",
                                "path": "../secret",
                            }
                        ]
                    }
                }
            )


if __name__ == "__main__":
    unittest.main()
