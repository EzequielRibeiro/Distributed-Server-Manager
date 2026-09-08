#!/usr/bin/env python3
"""Source-level parity guards for the Hybrid Customer Workspace P0."""
from __future__ import annotations

import re
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
if str(DASHBOARD) not in sys.path:
    sys.path.insert(0, str(DASHBOARD))

from json_serialization import to_json_compatible


class HybridCustomerWorkspaceParityTest(unittest.TestCase):
    def test_hybrid_polkit_rule_is_scoped_to_instance_units(self):
        source = (ROOT / "installer" / "install_hybrid_runtime_substrate.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "var instanceUnit = /^capivara-instance-[A-Za-z0-9._-]{1,191}\\\\.service$/;",
            source,
        )
        self.assertIn("instanceUnit.test(unit)", source)
        self.assertNotIn('unit.indexOf("capivara-instance-") === 0', source)
        self.assertNotIn('unit.indexOf("capivara-instance-") == 0', source)

    def test_hybrid_agent_state_allows_runtime_traversal_without_listing(self):
        source = (ROOT / "installer" / "install_hybrid_runtime_substrate.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'install -d -m 0710 -o "${DSM_USER}" -g capivara-agent \\\n  "${DSM_ROOT}/runtime/hybrid-agent-state"',
            source,
        )
        self.assertIn(
            '"${DSM_ROOT}/runtime/hybrid-agent-state/backups"',
            source,
        )
        self.assertIn(
            '"${DSM_ROOT}/runtime/hybrid-agent-state/backup-results"',
            source,
        )
        self.assertNotIn(
            'install -d -m 0750 -o "${DSM_USER}" -g capivara-agent \\\n  "${DSM_ROOT}/runtime/hybrid-agent-state"',
            source,
        )

    def test_workspace_http_normalizes_database_native_values(self):
        source = (DASHBOARD / "customer_instance_workspace_http.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("to_json_compatible(payload)", source)
        self.assertIn('getattr(self,"_internal_error",None)', source)
        payload = {
            "created_at": datetime(2026, 9, 8, 9, 0, tzinfo=timezone.utc),
            "ratio": Decimal("1.25"),
            "nested": [{"completed_at": datetime(2026, 9, 8, 9, 1)}],
        }
        normalized = to_json_compatible(payload)
        self.assertEqual(normalized["ratio"], 1.25)
        self.assertIsInstance(normalized["created_at"], str)
        self.assertIsInstance(normalized["nested"][0]["completed_at"], str)

    def test_artifact_http_normalizes_transfer_and_restore_payloads(self):
        source = (DASHBOARD / "artifact_transfer_http.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("to_json_compatible(payload)", source)
        self.assertIn("restore_job\":job", source)

    def test_customer_instance_workspace_has_no_inline_style_mutation(self):
        paths = [
            DASHBOARD / "web" / "customer-instance.html",
            DASHBOARD / "web" / "customer-instance-v2.js",
            DASHBOARD / "web" / "customer-backup-transfer.js",
            DASHBOARD / "web" / "customer-instance-delete.js",
        ]
        for path in paths:
            source = path.read_text(encoding="utf-8")
            self.assertIsNone(
                re.search(r"\bstyle\s*=", source, re.IGNORECASE),
                path.name,
            )
            if path.suffix == ".js":
                self.assertNotIn(".style.", source, path.name)
        html = paths[0].read_text(encoding="utf-8")
        self.assertIn('<progress id="provision-bar"', html)
        self.assertIn('<progress id="storage-bar"', html)
        self.assertIn('<progress id="files-storage-bar"', html)

    def test_restart_control_requires_explicit_permission(self):
        source = (DASHBOARD / "web" / "customer-instance-v2.js").read_text(
            encoding="utf-8"
        )
        self.assertIn('async function control(action){if(!can(`instance.${action}`))return;', source)
        self.assertNotIn('&&action!=="restart"', source)


if __name__ == "__main__":
    unittest.main()
