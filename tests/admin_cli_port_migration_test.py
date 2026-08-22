#!/usr/bin/env python3
"""Small contract check for migration 041 parity."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
files = [ROOT / "database/schemas" / f"{backend}.sql"
         for backend in ("sqlite", "postgresql", "mysql", "mariadb")]
for path in files:
    text = path.read_text(encoding="utf-8")
    assert "deleting" in text, path
    assert "remove" in text, path
    assert "agent_instance_commands" in text, path
print("admin_cli_port_migration_test: ok")
