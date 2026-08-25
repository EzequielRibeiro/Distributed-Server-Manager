#!/usr/bin/env python3
from __future__ import annotations

import base64
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from dashboard_activity_http import (
    ACTIVITY_API,
    ACTIVITY_OPTIONS_API,
    ACTIVITY_PAGE,
    LOGOUT_API,
    _activity,
    _category,
    _requested_username,
    _session_id,
    _should_record,
)
from dashboard_activity_repository import DashboardActivityRepository
from runtime_backend import backend_from_environment
from schema_baseline import load_schema_baseline


class HeaderStub(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class DashboardActivityAuditTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "audit.db"
        self.backend = backend_from_environment({
            "DSM_DATABASE_DRIVER": "sqlite",
            "DSM_DATABASE": str(self.database),
        })
        self.backend.initialize()
        self.repo = DashboardActivityRepository(self.backend)

    def tearDown(self):
        self.temp.cleanup()

    def record(self, **overrides):
        values = {
            "username": "admin.one",
            "role": "admin",
            "session_id": "session-a",
            "activity": "PAGE_VIEW",
            "category": "navigation",
            "result": "success",
            "method": "GET",
            "path": "/users.html",
            "status_code": 200,
            "remote_address": "192.0.2.10",
            "user_agent": "Audit Test Browser",
        }
        values.update(overrides)
        return self.repo.record(**values)

    def test_record_and_query_are_persisted_in_database(self):
        event_id = self.record()
        rows = self.repo.search(username="admin.one")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event_id"], event_id)
        self.assertEqual(rows[0]["activity"], "PAGE_VIEW")
        self.assertEqual(rows[0]["remote_address"], "192.0.2.10")
        self.assertEqual(rows[0]["details"], {})

    def test_filters_support_user_activity_category_result_and_date(self):
        self.record(username="operator.one", activity="POST:api.instance.start", category="instances")
        login_event = self.record(username="admin.one", activity="LOGIN", category="authentication")
        rows = self.repo.search(username="admin.one", activity="LOGIN", category="authentication", result="success")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["username"], "admin.one")
        created_at = str(rows[0]["created_at"])
        dated = self.repo.search(start_at=created_at, end_at=created_at)
        self.assertTrue(any(item["event_id"] == login_event for item in dated))
        self.assertEqual(self.repo.search(username="nobody"), [])

    def test_filter_options_are_database_driven(self):
        self.record(username="admin.one", activity="LOGIN", category="authentication")
        self.record(username="operator.one", activity="PAGE_VIEW", category="navigation")
        options = self.repo.filter_options()
        self.assertEqual(options["users"], ["admin.one", "operator.one"])
        self.assertIn("LOGIN", options["activities"])
        self.assertIn("PAGE_VIEW", options["activities"])
        self.assertIn("authentication", options["categories"])

    def test_credentials_and_session_secret_are_not_exposed_by_helpers(self):
        raw = "admin.one:SuperSecretPassword!"
        basic = base64.b64encode(raw.encode()).decode()
        username = _requested_username(HeaderStub({"Authorization": f"Basic {basic}"}))
        self.assertEqual(username, "admin.one")
        self.assertNotIn("SuperSecretPassword", username)
        token = "very-secret-session-token"
        correlated = _session_id(token)
        self.assertIsNotNone(correlated)
        self.assertNotEqual(correlated, token)
        self.assertNotIn(token, correlated)
        self.assertEqual(len(correlated), 32)

    def test_mapping_covers_login_logout_navigation_and_major_domains(self):
        self.assertEqual(_activity("POST", "/api/auth/login"), "LOGIN")
        self.assertEqual(_activity("POST", LOGOUT_API), "LOGOUT")
        self.assertEqual(_activity("GET", "/users.html"), "PAGE_VIEW")
        self.assertEqual(_category("/api/users/save"), "system_users")
        self.assertEqual(_category("/api/catalog/resource-profiles"), "catalog")
        self.assertEqual(_category("/api/instance/start"), "instances")
        self.assertEqual(_category("/api/backup"), "backup")
        self.assertEqual(_category("/activity-log.html"), "navigation")

    def test_human_activity_policy_excludes_machine_polling(self):
        user = {"username": "admin.one", "role": "admin"}
        self.assertTrue(_should_record("POST", "/api/auth/login", None))
        self.assertTrue(_should_record("POST", LOGOUT_API, user))
        self.assertTrue(_should_record("GET", "/users.html", user))
        self.assertTrue(_should_record("POST", "/api/users/save", user))
        for route in ("/ping", "/health", "/api/controller/telemetry", "/api/realtime/events"):
            self.assertFalse(_should_record("GET", route, user), route)

    def test_activity_schema_exists_in_every_database_baseline(self):
        required = (
            "dashboard_activity_log",
            "idx_dashboard_activity_created",
            "idx_dashboard_activity_user_created",
            "idx_dashboard_activity_category_created",
            "idx_dashboard_activity_session_created",
            "remote_address",
            "user_agent",
            "session_id",
            "activity",
            "category",
            "result",
        )
        for backend in ("postgresql", "sqlite", "mysql", "mariadb"):
            sql = load_schema_baseline(backend).sql.lower()
            for token in required:
                self.assertIn(token, sql, f"{backend} missing {token}")

    def test_admin_query_surface_and_privacy_contract_are_present(self):
        http_source = (ROOT / "dashboard" / "dashboard_activity_http.py").read_text(encoding="utf-8")
        page_source = (ROOT / "dashboard" / "web" / "activity-log.html").read_text(encoding="utf-8")
        sidebar = (ROOT / "dashboard" / "web" / "components" / "sidebar-v3.html").read_text(encoding="utf-8")
        self.assertIn(ACTIVITY_PAGE.lstrip("/"), sidebar)
        self.assertIn(ACTIVITY_API, http_source)
        self.assertIn(ACTIVITY_OPTIONS_API, http_source)
        self.assertIn("Acesso exclusivo de administradores", http_source)
        self.assertIn("Senhas, hashes, tokens, cookies", page_source)
        self.assertNotIn("details_json = self.read_json_body", http_source)


if __name__ == "__main__":
    unittest.main()
