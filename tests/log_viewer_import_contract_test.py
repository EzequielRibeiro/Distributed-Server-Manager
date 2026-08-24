#!/usr/bin/env python3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_agent_log_viewer_imports_database_helpers_it_uses():
    source = (ROOT / "dashboard" / "server.py").read_text(encoding="utf-8")
    assert "from alert_repository import AlertSession, dialect_for_backend" in source
    assert "dialect = dialect_for_backend(backend)" in source
    assert "session = AlertSession(backend, connection)" in source
