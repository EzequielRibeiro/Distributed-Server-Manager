#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "database", ROOT / "core"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from operation_diagnostic_repository import _sanitize
from operation_diagnostics_schema import operation_diagnostics_ddl
from baseline_upgrade_engine import latest_upgrade_version


class OperationDiagnosticsTest(unittest.TestCase):
    def test_diagnostic_payload_redacts_secret_fields(self):
        value = _sanitize({
            "error": "failure",
            "password": "dont-store-me",
            "nested": {"api_key": "secret", "safe": "ok"},
        })
        self.assertEqual(value["password"], "<redacted>")
        self.assertEqual(value["nested"]["api_key"], "<redacted>")
        self.assertEqual(value["nested"]["safe"], "ok")

    def test_schema_exists_for_every_supported_database(self):
        for backend in ("sqlite", "postgresql", "mysql"):
            ddl = operation_diagnostics_ddl(backend)
            self.assertIn("operation_diagnostics", ddl)
            self.assertIn("traceback", ddl)
            self.assertIn("technical_detail", ddl)
            self.assertIn("compensation_json", ddl)

    def test_operation_diagnostics_is_baseline_upgrade_18(self):
        self.assertEqual(latest_upgrade_version(), 18)

    def test_privileged_materializer_propagates_helper_error(self):
        source = (ROOT / "agents/linux/runtime/privileged_materialization.py").read_text(encoding="utf-8")
        self.assertIn('failed_result.get("error")', source)
        self.assertIn("helper_error or completed.stderr", source)

    def test_alert_ui_exposes_diagnostic_and_copy_action(self):
        js = (ROOT / "dashboard/web/observability.js").read_text(encoding="utf-8")
        html = (ROOT / "dashboard/web/alerts.html").read_text(encoding="utf-8")
        self.assertIn("Ver detalhes", js)
        self.assertIn("Copiar diagnóstico", html)
        self.assertIn("Traceback", js)
        self.assertIn("Compensações", js)


if __name__ == "__main__":
    unittest.main()
