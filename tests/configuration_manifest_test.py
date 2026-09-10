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

class ManagedConfigurationManifestTest(unittest.TestCase):
    def test_managed_properties_are_loaded(self):
        manifest = ConfigurationManifest.from_runtime_definition(
            {
                "configuration": {
                    "files": [
                        {
                            "id": "server",
                            "path": "serverDZ.cfg",
                            "editable": False,
                            "format": "semicolon_properties",
                            "properties": [
                                {
                                    "key": "hostname",
                                    "source": "CUSTOMER",
                                    "type": "string",
                                },
                                {
                                    "key": "maxPlayers",
                                    "source": "CONTRACT",
                                    "type": "integer",
                                },
                                {
                                    "key": "steamQueryPort",
                                    "source": "SYSTEM",
                                    "type": "integer",
                                },
                            ],
                        }
                    ]
                }
            }
        )

        entry = manifest.entries[0]

        self.assertFalse(entry.editable)
        self.assertEqual(entry.format, "semicolon_properties")
        self.assertEqual(
            [(p.key, p.source, p.type) for p in entry.properties],
            [
                ("hostname", "CUSTOMER", "string"),
                ("maxPlayers", "CONTRACT", "integer"),
                ("steamQueryPort", "SYSTEM", "integer"),
            ],
        )

    def test_unknown_property_source_is_rejected(self):
        with self.assertRaises(ConfigurationManifestError):
            ConfigurationManifest.from_runtime_definition(
                {
                    "configuration": {
                        "files": [
                            {
                                "id": "server",
                                "path": "serverDZ.cfg",
                                "format": "semicolon_properties",
                                "properties": [
                                    {
                                        "key": "hostname",
                                        "source": "AGENT",
                                    }
                                ],
                            }
                        ]
                    }
                }
            )

    def test_duplicate_property_keys_are_rejected(self):
        with self.assertRaises(ConfigurationManifestError):
            ConfigurationManifest.from_runtime_definition(
                {
                    "configuration": {
                        "files": [
                            {
                                "id": "server",
                                "path": "serverDZ.cfg",
                                "format": "semicolon_properties",
                                "properties": [
                                    {
                                        "key": "hostname",
                                        "source": "CUSTOMER",
                                    },
                                    {
                                        "key": "hostname",
                                        "source": "SYSTEM",
                                    },
                                ],
                            }
                        ]
                    }
                }
            )

    def test_unknown_managed_format_is_rejected(self):
        with self.assertRaises(ConfigurationManifestError):
            ConfigurationManifest.from_runtime_definition(
                {
                    "configuration": {
                        "files": [
                            {
                                "id": "server",
                                "path": "serverDZ.cfg",
                                "format": "unknown-format",
                            }
                        ]
                    }
                }
            )

    def test_properties_require_format(self):
        with self.assertRaises(ConfigurationManifestError):
            ConfigurationManifest.from_runtime_definition(
                {
                    "configuration": {
                        "files": [
                            {
                                "id": "server",
                                "path": "serverDZ.cfg",
                                "properties": [
                                    {
                                        "key": "hostname",
                                        "source": "CUSTOMER",
                                    }
                                ],
                            }
                        ]
                    }
                }
            )
