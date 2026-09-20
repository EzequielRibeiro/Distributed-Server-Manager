#!/usr/bin/env python3
"""DB1-DB6 Database Intelligence contract and SQLite parity tests."""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend import DatabaseConfig
from backend_factory import create_backend
from database_intelligence_api import _require_admin, _require_manager, database_intelligence, database_maintenance
from database_intelligence_repository import DatabaseIntelligenceRepository


class DatabaseIntelligenceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "capivara.db"
        self.backend = create_backend(DatabaseConfig(driver="sqlite", database=str(self.db)))
        self.backend.initialize()
        self.repo = DatabaseIntelligenceRepository(self.backend)

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_db1_health_and_storage(self):
        health = self.repo.health()
        self.assertEqual(health["backend"], "sqlite")
        self.assertEqual(health["health"], "healthy")
        self.assertGreaterEqual(health["database_size_bytes"], 0)
        storage = self.repo.storage()
        self.assertTrue(any(row["table_name"] == "observability_samples" for row in storage["tables"]))

    def test_db2_snapshot_and_growth(self):
        one = self.repo.capture_snapshot(datetime(2026, 9, 19, tzinfo=timezone.utc))
        self.assertGreater(one["rows"], 1)
        with self.backend.transaction() as connection:
            connection.execute(
                "UPDATE database_metrics_daily SET database_size_bytes=? "
                "WHERE snapshot_day=? AND table_name='@database'",
                (1000, "2026-09-19"),
            )
        self.repo.capture_snapshot(datetime(2026, 9, 20, tzinfo=timezone.utc))
        growth = self.repo.growth(days=30)
        self.assertEqual(len(growth["series"]), 2)
        self.assertIn("30", growth["forecast_bytes"])

    def test_db5_insights_and_db6_capabilities(self):
        insights = self.repo.insights()
        self.assertTrue(insights)
        caps = self.repo.capabilities()
        self.assertTrue(caps["health"])
        self.assertTrue(caps["growth_snapshots"])
        self.assertFalse(caps["physical_reclaim_action"])
        self.assertFalse(caps["index_scan_stats"])

    def test_read_roles_and_admin_only_maintenance(self):
        self.assertEqual(_require_manager({"role": "controller"})["role"], "controller")
        with self.assertRaises(PermissionError):
            _require_manager({"role": "customer"})
        with self.assertRaises(PermissionError):
            _require_admin({"role": "controller"})
        overview = database_intelligence(user={"role": "admin"}, backend=self.backend)
        self.assertEqual(overview["kind"], "CapivaraDatabaseIntelligence")
        result = database_maintenance(
            user={"role": "admin", "username": "admin"},
            backend=self.backend,
            action="snapshot",
        )
        self.assertGreater(result["rows"], 1)

    def test_db4_analyze_is_safe_and_bounded(self):
        result = database_maintenance(
            user={"role": "admin", "username": "admin"},
            backend=self.backend,
            action="analyze",
        )
        self.assertEqual(result["action"], "analyze")
        self.assertGreaterEqual(result["completed"], 1)


class DatabaseIntelligenceBrowserContractTest(unittest.TestCase):
    def test_page_and_http_surface_are_composed(self):
        page = (ROOT / "dashboard" / "web" / "database-intelligence.html").read_text(encoding="utf-8")
        script = (ROOT / "dashboard" / "web" / "database-intelligence.js").read_text(encoding="utf-8")
        service = (ROOT / "systemd" / "dsm-dashboard.service").read_text(encoding="utf-8")
        sidebar = (ROOT / "dashboard" / "web" / "components" / "sidebar-v3.html").read_text(encoding="utf-8")
        self.assertIn("Database Intelligence", page)
        self.assertIn("/api/admin/database-intelligence", script)
        self.assertIn("X-Capivara-Auth-Area", script)
        self.assertIn("server_part22.py", service)
        self.assertIn("database-intelligence.html", sidebar)

    def test_mobile_layout_and_human_labels_are_present(self):
        script = (ROOT / "dashboard" / "web" / "database-intelligence.js").read_text(encoding="utf-8")
        css = (ROOT / "dashboard" / "web" / "database-intelligence.css").read_text(encoding="utf-8")
        self.assertIn("dashboard_activity_log:'Atividade do painel'", script)
        self.assertIn("observability_samples:'Histórico de telemetria'", script)
        self.assertIn("CAPABILITY_LABELS", script)
        self.assertIn('data-label="Tabela"', script)
        self.assertIn("@media(max-width:480px)", css)
        self.assertIn(".table-wrap thead{display:none}", css)
        self.assertIn("overflow-wrap:anywhere", css)

    def test_physical_reclaim_is_not_exposed_as_action(self):
        source = (ROOT / "dashboard" / "database_intelligence_api.py").read_text(encoding="utf-8")
        page = (ROOT / "dashboard" / "web" / "database-intelligence.html").read_text(encoding="utf-8")
        self.assertNotIn('normalized == "vacuum-full"', source.lower())
        self.assertNotIn('normalized == "reindex"', source.lower())
        self.assertIn("VACUUM FULL", page)
        self.assertIn("REINDEX", page)


if __name__ == "__main__":
    unittest.main()
