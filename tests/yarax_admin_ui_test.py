#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
DATABASE = ROOT / "database"

for path in (str(DASHBOARD), str(DATABASE)):
    if path not in sys.path:
        sys.path.insert(0, path)

from yarax_security_api import yarax_security_overview
from yarax_security_http import dispatch_yarax_security_get


class FakeBackend:
    name = "sqlite"

    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(
            """
            CREATE TABLE agents(id TEXT PRIMARY KEY,name TEXT,status TEXT);
            CREATE TABLE agent_runtime_inventory(
                agent_id TEXT PRIMARY KEY,
                health_status TEXT,
                capivara_version TEXT,
                last_seen TEXT,
                capabilities_json TEXT
            );
            """
        )
        self.db.execute("INSERT INTO agents VALUES('agent-a','Agent A','active')")
        capabilities = {
            "content_security": {
                "ready": True,
                "state": "ready",
                "engine_version": "1.20.0",
                "engine_pinned_version": "1.20.0",
                "engine_managed": True,
                "ruleset_version": "2026.09.18.1",
                "ruleset_pinned_version": "2026.09.18.1",
                "rules_count": 1,
                "ruleset_checksum_valid": True,
                "rules_managed": True,
                "last_error": None,
            },
            "secret": "must-not-leak",
        }
        self.db.execute(
            "INSERT INTO agent_runtime_inventory VALUES(?,?,?,?,?)",
            ("agent-a","online","2.0.70","2026-09-18T22:00:00Z",json.dumps(capabilities)),
        )
        self.db.commit()

    def connect(self):
        backend = self
        class Context:
            def __enter__(self):
                return backend.db
            def __exit__(self, *args):
                return False
        return Context()


class YaraXAdminUiTest(unittest.TestCase):
    def test_admin_only(self):
        backend = FakeBackend()
        with self.assertRaises(PermissionError):
            yarax_security_overview(user={"role":"customer"}, backend=backend)
        status, body = dispatch_yarax_security_get(
            "/api/admin/security/yara-x", "",
            user={"role":"customer"}, backend=backend,
        )
        self.assertEqual(status, 403)
        self.assertEqual(body["error"], "forbidden")

    def test_overview_exposes_safe_agent_security_and_scan_activity(self):
        backend = FakeBackend()
        events = [
            {
                "event_id":"e1","event_type":"YARAX_SCAN_COMPLETED",
                "occurred_at":"2026-09-18T22:10:00Z","severity":"info",
                "agent_id":"agent-a","instance_id":"i1","correlation_id":"c1",
                "data":{
                    "content_id":"vpp","provider":"steam-workshop","game_id":"dayz",
                    "result":"clean","duration_ms":42,"target_kind":"directory",
                    "engine_version":"1.20.0","ruleset_version":"2026.09.18.1",
                    "matches":[{"rule":"Example_Stealer","tags":["malware","block"],"file_name":"evil.dll","relative_path":"mods/evil.dll","detection_name":"Example Stealer","threat_name":"Example Stealer","malware_family":"ExampleFamily","category":"infostealer","description":"Credential stealer"}],
                },
            },
            {"event_id":"e2","event_type":"SOMETHING_ELSE","data":{}},
        ]
        with patch("yarax_security_api.UniversalEventRepository") as repo_cls:
            repo = repo_cls.return_value
            repo.list_events.return_value = events
            result = yarax_security_overview(user={"role":"admin"}, backend=backend)
        self.assertEqual(result["kind"], "CapivaraYaraXSecurityOverview")
        self.assertEqual(result["summary"]["agents_ready"], 1)
        self.assertEqual(result["summary"]["results"]["clean"], 1)
        self.assertEqual(len(result["events"]), 1)
        event = result["events"][0]
        self.assertEqual(event["matched_files"], ["mods/evil.dll"])
        self.assertEqual(event["matches"][0]["threat_name"], "Example Stealer")
        self.assertEqual(event["matches"][0]["malware_family"], "ExampleFamily")
        self.assertEqual(event["matches"][0]["category"], "infostealer")
        agent = result["agents"][0]
        self.assertEqual(agent["engine_version"], "1.20.0")
        self.assertEqual(agent["ruleset_version"], "2026.09.18.1")
        self.assertNotIn("secret", json.dumps(agent))

    def test_result_filter_is_server_side(self):
        backend = FakeBackend()
        events = [
            {"event_id":"e1","event_type":"YARAX_SCAN_COMPLETED","agent_id":"agent-a","data":{"result":"clean"}},
            {"event_id":"e2","event_type":"YARAX_SCAN_COMPLETED","agent_id":"agent-a","data":{"result":"blocked"}},
        ]
        with patch("yarax_security_api.UniversalEventRepository") as repo_cls:
            repo_cls.return_value.list_events.return_value = events
            result = yarax_security_overview(
                user={"role":"controller"}, backend=backend, filters={"result":"blocked"}
            )
        self.assertEqual([e["result"] for e in result["events"]], ["blocked"])

    def test_ui_contract_and_canonical_composition(self):
        page = (DASHBOARD / "web" / "admin-security-yarax.html").read_text(encoding="utf-8")
        script = (DASHBOARD / "web" / "admin-security-yarax.js").read_text(encoding="utf-8")
        http = (DASHBOARD / "yarax_security_http.py").read_text(encoding="utf-8")
        part = (DASHBOARD / "server_part21.py").read_text(encoding="utf-8")
        service = (ROOT / "systemd" / "dsm-dashboard.service").read_text(encoding="utf-8")
        self.assertIn("Segurança · Universal Content", page)
        self.assertIn("/api/admin/security/yara-x", script)
        self.assertIn("<th>Arquivo</th>", page)
        self.assertIn("<th>Detecção</th>", page)
        self.assertIn("function detectionDetails(row)", script)
        self.assertIn("Ameaça:", script)
        self.assertIn("Família:", script)
        self.assertIn("Regra:", script)
        self.assertIn("YARAX_SECURITY_PAGE", http)
        self.assertIn("import server_part20 as integration", part)
        self.assertIn(
            "integration.integration.integration.integration._controller_authenticate",
            part.replace("\\n", " "),
        )
        self.assertIn("server_part21.py", service)


    def test_admin_sidebar_exposes_yarax_security_navigation(self):
        for name in ("sidebar-v3.html", "sidebar.html"):
            sidebar = (
                DASHBOARD / "web" / "components" / name
            ).read_text(encoding="utf-8")
            self.assertIn('<div class="cap-nav-group-title">Segurança</div>', sidebar)
            self.assertIn('href="admin-security-yarax.html"', sidebar)
            self.assertIn("<span>YARA-X</span>", sidebar)


    def test_yarax_static_assets_are_served_without_browser_auth_gate(self):
        source = (DASHBOARD / "yarax_security_http.py").read_text(encoding="utf-8")
        self.assertIn('YARAX_SECURITY_ASSETS = {"/admin-security-yarax.js", "/admin-security-yarax.css"}', source)
        asset_index = source.index("if parsed.path in YARAX_SECURITY_ASSETS:")
        auth_index = source.index("user = authenticate(self.headers)", asset_index)
        self.assertLess(asset_index, auth_index)
        self.assertIn("self.send_file(legacy.STATIC_FILES[parsed.path])", source)

    def test_yarax_browser_api_uses_controller_session_boundary(self):
        script = (DASHBOARD / "web" / "admin-security-yarax.js").read_text(encoding="utf-8")
        self.assertIn("'X-Capivara-Auth-Area':'controller'", script)
        self.assertIn("credentials:'same-origin'", script)
        self.assertIn("cache:'no-store'", script)

    def test_yarax_activity_refreshes_automatically(self):
        script = (DASHBOARD / "web" / "admin-security-yarax.js").read_text(encoding="utf-8")
        self.assertIn("const LIVE_REFRESH_MS = 10000", script)
        self.assertIn("setInterval(liveRefresh, LIVE_REFRESH_MS)", script)
        self.assertIn("document.hidden", script)
        self.assertIn("visibilitychange", script)
        self.assertIn("if (loadInFlight) return", script)
        self.assertIn("finally {", script)

    def test_yarax_page_uses_canonical_admin_shell(self):
        page = (DASHBOARD / "web" / "admin-security-yarax.html").read_text(encoding="utf-8")
        script = (DASHBOARD / "web" / "admin-security-yarax.js").read_text(encoding="utf-8")
        self.assertIn('/dashboard-home-v3.css', page)
        self.assertIn('id="sidebar-component"', page)
        self.assertIn('class="cap-home cap-yarax-admin"', page)
        self.assertIn('id="yarax-menu-toggle"', page)
        self.assertIn("loadShell()", script)
        self.assertIn("'/components/sidebar-v3.html'", script)

    def test_api_does_not_expose_file_contents_or_credentials(self):
        source = (DASHBOARD / "yarax_security_api.py").read_text(encoding="utf-8")
        for forbidden in ("credential_secret", "pairing_token", "file_content", "artifact_bytes"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
