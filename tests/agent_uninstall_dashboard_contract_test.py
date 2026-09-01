#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_admin_http_exposes_typed_remote_uninstall_and_controller_only_remove():
    source = (ROOT / "dashboard" / "agent_admin_http.py").read_text(encoding="utf-8")
    assert 'UNINSTALL_PATH = "/api/admin/agent/uninstall"' in source
    assert "request_agent_uninstall(" in source
    assert "force_remove_controller_registration(" in source
    assert 'event_type="AGENT_REMOTE_UNINSTALL_REQUESTED"' in source
    assert 'event_type="AGENT_CONTROLLER_REGISTRATION_REMOVED"' in source


def test_danger_zone_splits_remote_uninstall_from_forced_deregistration():
    html = (ROOT / "dashboard" / "web" / "agent-details.html").read_text(encoding="utf-8")
    javascript = (ROOT / "dashboard" / "web" / "agent-uninstall-admin.js").read_text(encoding="utf-8")

    assert 'id="agent-uninstall-preserve"' in html
    assert 'id="agent-uninstall-purge"' in html
    assert 'id="agent-force-remove"' in html
    assert 'id="agent-remove"' not in html
    assert 'agent-uninstall-admin.js?v=1' in html

    assert 'uninstall("preserve-data")' in javascript
    assert 'uninstall("purge")' in javascript
    assert 'request("/api/admin/agent/uninstall"' in javascript
    assert 'request("/api/admin/agent/remove"' in javascript
    assert "result.controller_only" in javascript
    assert "result.remote_host_removal !== false" in javascript
