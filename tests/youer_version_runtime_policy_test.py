#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from dashboard.catalog_provisioning_resolver import resolve_catalog_provisioning


class YouerVersionRuntimePolicyTest(unittest.TestCase):
    def test_youer_26_2_provisioning_selects_java_25(self):
        selection = {
            "schema_version": 2,
            "kind": "RuntimeSelection",
            "environment_id": "minecraft.java.youer",
            "runtime_definition": "minecraft.java.youer",
            "game": "minecraft",
            "version": "26.2",
            "build": "791",
            "provider": "http",
        }
        _, config = resolve_catalog_provisioning(
            environment_id="minecraft.java.youer",
            selector="26.2@791",
            selection=selection,
            configuration={},
            root=ROOT,
        )
        self.assertEqual(
            config["catalog_runtime_policy"]["requirements"]["java"],
            {"min": 25, "max": 25},
        )

    def test_youer_1_21_1_provisioning_keeps_java_21(self):
        selection = {
            "schema_version": 2,
            "kind": "RuntimeSelection",
            "environment_id": "minecraft.java.youer",
            "runtime_definition": "minecraft.java.youer",
            "game": "minecraft",
            "version": "1.21.1",
            "build": "657",
            "provider": "http",
        }
        _, config = resolve_catalog_provisioning(
            environment_id="minecraft.java.youer",
            selector="1.21.1@657",
            selection=selection,
            configuration={},
            root=ROOT,
        )
        self.assertEqual(
            config["catalog_runtime_policy"]["requirements"]["java"],
            {"min": 21, "max": 21},
        )


if __name__ == "__main__":
    unittest.main()
