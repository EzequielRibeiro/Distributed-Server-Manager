#!/usr/bin/env python3
"""PR #1071 fixed final gates; no live Agent or production database access."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import patch

from tests import instance_agent_relocation_test as fixture
ROOT = fixture.ROOT
from instance_agent_relocation_http import PATH, install_instance_agent_relocation_http
from instance_agent_relocation_repository import InstanceAgentRelocationRepository, RelocationConflict
from backend import DatabaseConfig
from backend_factory import create_backend


class PR1071FinalGatesTest(unittest.TestCase):
    setUp = fixture.AgentRelocationTest.setUp
    enqueue = fixture.AgentRelocationTest.enqueue

    def test_http_authorization_confirmation_gate_and_read_only_diagnostics(self):
        item = self.enqueue()
        rid = item["relocation_id"]
        self.repo._set(rid, status="manual_recovery")
        class Handler:
            def __init__(self, actor=None, data=None, path=PATH):
                self.headers = {"auth": actor}
                self.payload = data or {}
                self.path = path
                self.response = None
            def do_GET(self):
                raise AssertionError("unexpected GET route")
            def do_POST(self):
                raise AssertionError("unexpected POST route")
            def read_json_body(self):
                return self.payload
            def send_json(self, code, payload):
                self.response = (code, payload)
            def unauthorized(self):
                self.response = (401, {})
        legacy = SimpleNamespace(
            DashboardHandler=Handler,
            dashboard_repository=lambda _: SimpleNamespace(backend=self.backend),
            DATABASE_FILE=str(self.root / "test.db"), DSM_ROOT=ROOT,
            audit=lambda *args: None,
        )
        install_instance_agent_relocation_http(legacy, lambda h: h["auth"])
        admin = {"role": "admin", "username": "admin"}
        request = {"action": "recover_pre_cutover", "relocation_id": rid, "confirmation": "server-1"}
        before = self.repo.get(rid)

        with patch.dict(os.environ, {"CAPIVARA_ENABLE_AGENT_RELOCATION": ""}):
            h = Handler(admin, path=PATH + "?relocation_id=" + rid + "&recovery_diagnostics=1")
            h.do_GET()
            self.assertEqual(h.response[0], 200)
            self.assertFalse(h.response[1]["recovery"]["automatic_unfence_allowed"])
            self.assertEqual(self.repo.get(rid), before)
            h = Handler(admin, request)
            h.do_POST()
            self.assertEqual(h.response[0], 423)

        with patch.dict(os.environ, {"CAPIVARA_ENABLE_AGENT_RELOCATION": "1"}):
            for actor in (
                {"role": "customer"},
                {"role": "controller", "scope_id": "ctrl-2"},
            ):
                h = Handler(actor, request)
                h.do_POST()
                self.assertEqual(h.response[0], 403)
            h = Handler(admin, dict(request, confirmation="wrong"))
            h.do_POST()
            self.assertEqual(h.response[0], 400)
            self.assertEqual(self.repo.get(rid)["status"], "manual_recovery")
            with patch.object(InstanceAgentRelocationRepository, "_lifecycle",
                              side_effect=AssertionError("unexpected unfence")):
                h = Handler(admin, request)
                h.do_POST()
            self.assertEqual(h.response[0], 202)
            self.assertEqual(h.response[1]["relocation"]["status"], "rolling_back")
            self.assertIsNone(self.repo.get(rid)["unfence_command_id"])

    def test_concurrent_operator_recovery_has_single_winner(self):
        item = self.enqueue()
        rid = item["relocation_id"]
        self.repo._set(rid, status="manual_recovery")
        gate = threading.Barrier(3)
        def request():
            gate.wait(timeout=10)
            try:
                return self.repo.request_safe_recovery(rid, confirmation="server-1")["status"]
            except RelocationConflict:
                return "conflict"
        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(request)
            b = pool.submit(request)
            gate.wait(timeout=10)
            results = [a.result(timeout=15), b.result(timeout=15)]
        self.assertCountEqual(results, ["rolling_back", "conflict"])
        self.assertEqual(self.repo.get(rid)["status"], "rolling_back")
        self.assertIsNone(self.repo.get(rid)["unfence_command_id"])

    def test_pg_transactional_recovery_and_lease_if_isolated_db_provided(self):
        sock = os.environ.get("DSM_PR1071_PG_SOCKET")
        if not sock:
            self.skipTest("Set DSM_PR1071_PG_SOCKET only for an isolated PostgreSQL fixture")
        port = int(os.environ.get("DSM_PR1071_PG_PORT", "55471"))
        dbname = os.environ.get("DSM_PR1071_PG_DATABASE", "pr1071_test")
        pg = create_backend(DatabaseConfig(
            driver="postgresql", database=dbname, host=sock, port=port,
            user=os.environ.get("USER", "ezequiel"), tls_mode="disable",
        ))
        pg.initialize()
        tables = (
            "nodes", "controllers", "agents", "customers", "instances",
            "service_contracts", "instance_contracts", "instance_ports",
            "agent_port_ranges", "backup_policies",
        )
        # Clone synthetic SQLite fixture only into the disposable PostgreSQL database.
        with self.backend.connect() as source, pg.transaction() as destination:
            for table in tables:
                types = {r["column_name"]: r["data_type"] for r in destination.execute(
                    "SELECT column_name,data_type FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name=%s "
                    "AND is_generated='NEVER'", (table,)
                ).fetchall()}
                for row in source.execute("SELECT * FROM " + table).fetchall():
                    fields = [name for name in row.keys() if row[name] is not None and name in types]
                    cols = ",".join(fields)
                    params = ",".join("%s" for _ in fields)
                    values = tuple(bool(row[name]) if types[name] == "boolean" else row[name]
                                   for name in fields)
                    conflict_clause = " ON CONFLICT DO NOTHING" if table == "agent_port_ranges" else ""
                    destination.execute(
                        f"INSERT INTO {table} ({cols}) VALUES ({params}){conflict_clause}",
                        values,
                    )
        repo = InstanceAgentRelocationRepository(pg, ROOT)
        with patch.object(repo, "preflight", return_value=self.plan), patch.object(
            repo, "_network_plan", return_value=self.target
        ):
            item = repo.enqueue("server-1", "target-agent",
                                requested_by="gate-test", confirmation="server-1")
        rid = item["relocation_id"]
        repo._set(rid, status="manual_recovery", lease_until=9999999999, lease_token="worker")
        with self.assertRaisesRegex(RelocationConflict, "lease"):
            repo.request_safe_recovery(rid, confirmation="server-1")
        repo._set(rid, lease_until=0, lease_token=None)
        with patch.object(repo, "_lifecycle", side_effect=AssertionError("unsafe lifecycle")):
            restored = repo.request_safe_recovery(rid, confirmation="server-1")
        self.assertEqual(restored["status"], "rolling_back")
        self.assertIsNone(restored["unfence_command_id"])
        self.assertEqual(repo.get(rid)["status"], "rolling_back")
        with self.assertRaises(RelocationConflict):
            repo.request_safe_recovery(rid, confirmation="server-1")


if __name__ == "__main__":
    unittest.main()
