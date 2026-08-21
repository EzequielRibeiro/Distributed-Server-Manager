#!/usr/bin/env python3

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import role_context


class RoleContextTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "config").mkdir()
        (self.root / "data").mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_environment_override_has_highest_precedence(self):
        (self.root / "config" / "dsm.conf").write_text('DSM_NODE_ROLE="controller"\n', encoding="utf-8")
        result = role_context.resolve_local_role(
            self.root, environ={"DSM_NODE_ROLE": "hybrid", "CAPIVARA_AGENT_CONFIG": "/missing"}
        )
        self.assertEqual(result["role"], "hybrid")
        self.assertEqual(result["source"], "env:DSM_NODE_ROLE")

    def test_persisted_role_is_read_without_sourcing_shell(self):
        marker = self.root / "should-not-exist"
        (self.root / "config" / "dsm.conf").write_text(
            f'DSM_NODE_ROLE="agent"\nEVIL="$(touch {marker})"\n', encoding="utf-8"
        )
        result = role_context.resolve_local_role(
            self.root, environ={"CAPIVARA_AGENT_CONFIG": "/missing"}
        )
        self.assertEqual(result["role"], "agent")
        self.assertFalse(marker.exists())

    def test_standalone_agent_config_resolves_agent(self):
        standalone = self.root / "standalone.json"
        standalone.write_text('{"agent_id":"agent-one"}', encoding="utf-8")
        result = role_context.resolve_local_role(
            self.root, environ={"CAPIVARA_AGENT_CONFIG": str(standalone)}
        )
        self.assertEqual(result["role"], "agent")
        self.assertEqual(result["source"], "config:standalone-agent")

    def test_legacy_sqlite_fallback_is_read_only(self):
        database = self.root / "data" / "capivara.db"
        connection = sqlite3.connect(database)
        connection.execute("CREATE TABLE nodes (id TEXT PRIMARY KEY, name TEXT, role TEXT)")
        connection.execute("INSERT INTO nodes(id,name,role) VALUES ('node-one','node-one','hybrid')")
        connection.commit()
        connection.close()
        (self.root / "config" / "dsm.conf").write_text(
            f'DSM_DATABASE_DRIVER="sqlite"\nDSM_DATABASE="{database}"\n', encoding="utf-8"
        )
        result = role_context.resolve_local_role(
            self.root, environ={"CAPIVARA_AGENT_CONFIG": "/missing"}
        )
        self.assertEqual(result["role"], "hybrid")
        self.assertEqual(result["source"], "legacy:sqlite-readonly")
        connection = sqlite3.connect(database)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM nodes").fetchone()[0], 1)
        connection.close()

    def test_ambiguous_legacy_agent_fails_closed(self):
        (self.root / "config" / "dsm.conf").write_text(
            'DSM_DATABASE_DRIVER="postgresql"\nDSM_NODE_ROLE=""\n', encoding="utf-8"
        )
        (self.root / "config" / "agent.conf").write_text('AGENT_ID="agent-old"\n', encoding="utf-8")
        result = role_context.resolve_local_role(
            self.root, environ={"CAPIVARA_AGENT_CONFIG": "/missing"}
        )
        self.assertEqual(result["role"], "unknown")
        self.assertEqual(result["source"], "legacy:agent-identity-ambiguous")


if __name__ == "__main__":
    unittest.main()
