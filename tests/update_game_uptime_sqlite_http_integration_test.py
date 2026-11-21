"""DSM #928: real Controller dispatcher, credential DB and SQLite heartbeat E2E.

Only an ephemeral 127.0.0.1 HTTP listener and temporary SQLite file are used.
This runs the actual AgentPairingRepository, authentication and dispatch_heartbeat
on both sides of a transport restart. It does not boot the full DSM web app,
migrate a production database, alter systemd or grant no-drain permission.
"""
from __future__ import annotations

import ast
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / "dashboard", ROOT / "database",
                  ROOT / "agents/linux/runtime", ROOT / "core"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from backend import DatabaseConfig
from backend_factory import create_backend
from registry import installation_profile_identity
from registry_repository import RegistryRepository
from agent_pairing_repository import AgentPairingRepository
from agent_remote_http import (dispatch_heartbeat, dispatch_fence_observation,
                               dispatch_enroll, dispatch_uninstall_result)
from game_uptime_agent_wire import build_probe, verify_offer
from game_uptime_controller_http_inflight import observe_controller_agent_inflight
from game_uptime_controller_agent_http_flock import (
    shared_controller_agent_http_lock, exclusive_controller_agent_http_lock,
    ControllerHttpLockUnavailable,
)
from prepare_controller_agent_http_lock import provision_controller_agent_http_lock


class ActualDispatcherSqliteHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dsm928-sqlite-controller-")
        self.addCleanup(self.temp.cleanup)
        self.db_path = Path(self.temp.name) / "controller.db"
        self.backend = create_backend(
            DatabaseConfig(driver="sqlite", database=str(self.db_path)))
        self.addCleanup(self._cleanup_backend)
        controller = installation_profile_identity(
            RegistryRepository(self.backend),
            profile="controller", hostname="dsm928-isolated-controller")
        pairing = AgentPairingRepository(self.backend)
        token = pairing.issue_token(controller_id=str(controller["controller_id"]),
                                    created_by="disposable-test")
        self.agent_id = getattr(self, "fixture_agent_id", "agent-928-sqlite")
        self.fingerprint = "sha256:dsm928-isolated-agent"
        self.identity = pairing.enroll(
            pairing_token=token.token, agent_id=self.agent_id,
            node_id="node-928-sqlite", name="DSM928 Isolated Agent",
            fingerprint=self.fingerprint, hostname="dsm928-agent-host",
            os_name="linux", architecture="x86_64", address="192.0.2.80",
        )
        self.server = None
        self.thread = None
        self._start_http()
        self.addCleanup(self._stop_http)

    def _cleanup_backend(self):
        if self.backend is not None:
            self.backend.close()
            self.backend = None

    def _start_http(self):
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                if self.path != "/api/agent/heartbeat":
                    self.send_error(404)
                    return
                try:
                    size = int(self.headers.get("Content-Length", "-1"))
                    if not (0 <= size <= 8192):
                        self.send_error(413)
                        return
                    body = json.loads(self.rfile.read(size))
                    status, payload = dispatch_heartbeat(
                        body, headers=self.headers, backend=fixture.backend)
                except (ValueError, UnicodeDecodeError):
                    status, payload = 400, {"error": "invalid_json"}
                data = json.dumps(payload, sort_keys=True).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:%d/api/agent/heartbeat" % self.server.server_port

    def _stop_http(self):
        if self.server is not None:
            self.server.shutdown()
            self.thread.join(timeout=4)
            self.server.server_close()
            self.server = None
            self.thread = None

    def _restart_controller_dispatcher(self):
        self._stop_http()
        self.backend.close()
        self.backend = create_backend(
            DatabaseConfig(driver="sqlite", database=str(self.db_path)))
        self._start_http()

    def _payload(self, **extra):
        payload = {
            "agent_id": self.agent_id, "hostname": "dsm928-agent-host",
            "os": "linux", "architecture": "x86_64",
            "capivara_version": "2.0.132", "fingerprint": self.fingerprint,
            "heartbeat_interval_seconds": 30, "degraded_after_seconds": 60,
            "offline_after_seconds": 120,
        }
        payload.update(extra)
        return payload

    def _request(self, payload, *, secret=None):
        req = Request(
            self.url,
            data=json.dumps(payload, sort_keys=True).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Capivara-Agent-Credential": self.identity.credential_id,
                "X-Capivara-Agent-Secret": (
                    self.identity.credential_secret if secret is None else secret),
                "X-Capivara-Agent-Fingerprint": self.fingerprint,
            },
            method="POST",
        )
        try:
            with urlopen(req, timeout=10) as response:
                return response.status, json.loads(response.read())
        except HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_credentialed_sqlite_controller_survives_restart_and_new_nonce(self):
        first = build_probe(self.agent_id)
        code, response = self._request(
            self._payload(no_drain_compatibility_probe=first))
        self.assertEqual(code, 200, response)
        offer = response["no_drain_compatibility_offer"]
        self.assertEqual(offer["status"], "wire_compatible")
        self.assertTrue(verify_offer(first, offer)["wire_compatible"])
        self.assertFalse(offer["live_no_drain_authorized"])
        with sqlite3.connect(self.db_path) as db:
            count = db.execute(
                "SELECT COUNT(*) FROM agent_runtime_inventory WHERE agent_id=?",
                (self.agent_id,)).fetchone()[0]
        self.assertEqual(count, 1)

        # New Controller backend and listener with the same durable DB.
        self._restart_controller_dispatcher()
        second = build_probe(self.agent_id)
        self.assertNotEqual(first["request_id"], second["request_id"])
        code, response = self._request(
            self._payload(no_drain_compatibility_probe=second))
        self.assertEqual(code, 200, response)
        new_offer = response["no_drain_compatibility_offer"]
        self.assertTrue(verify_offer(second, new_offer)["wire_compatible"])
        self.assertFalse(verify_offer(first, new_offer)["wire_compatible"])
        self.assertFalse(new_offer["live_no_drain_authorized"])
        self.assertEqual(response["health_status"], "online")

    def test_bad_real_database_credential_rejected_without_offer(self):
        probe = build_probe(self.agent_id)
        code, response = self._request(
            self._payload(no_drain_compatibility_probe=probe),
            secret="invalid-secret")
        self.assertEqual(code, 401, response)
        self.assertNotIn("no_drain_compatibility_offer", response)

    def test_identity_spoof_and_old_heartbeat_behavior(self):
        forged = build_probe("foreign-928-agent")
        code, response = self._request(
            self._payload(no_drain_compatibility_probe=forged))
        # The authenticated identity, never a probe's agent_id, controls the offer.
        self.assertEqual(code, 200, response)
        self.assertEqual(response["no_drain_compatibility_offer"]["agent_id"],
                         self.agent_id)
        self.assertEqual(response["no_drain_compatibility_offer"]["status"],
                         "blocked")
        # A forged main heartbeat identity also must not yield an offer.
        code, rejected = self._request(
            self._payload(agent_id="foreign-928-agent",
                          no_drain_compatibility_probe=forged))
        self.assertNotEqual(code, 200)
        self.assertNotIn("no_drain_compatibility_offer", rejected)
        code, legacy = self._request(self._payload())
        self.assertEqual(code, 200, legacy)
        self.assertEqual(legacy["health_status"], "online")
        self.assertNotIn("no_drain_compatibility_offer", legacy)


    def test_actual_controller_part11_post_route_with_durable_agent_credential(self):
        """Run the actual legacy.DashboardHandler integration function.

        Compiles the precise integrated_post function from server_part11.py
        into an isolated HTTP handler so importing the full dashboard app
        cannot start services or mutate global daemon handlers in the runner.
        DB auth and dispatch remain real. This is still *not* a full daemon.
        """
        self._stop_http()
        path = ROOT / "dashboard/server_part11.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        route = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "integrated_post"
        )
        route_code = compile(
            ast.Module(body=[route], type_ignores=[]), str(path), "exec"
        )
        fixture = self
        namespace = {
            "urlparse": urlparse,
            "CONSOLE_PUSH_PATH": "/api/agent/console/push",
            "ENROLL_PATH": "/api/agent/enroll",
            "HEARTBEAT_PATH": "/api/agent/heartbeat",
            "NO_DRAIN_OBSERVE_PATH": "/api/agent/no-drain/observe",
            "UNINSTALL_RESULT_PATH": "/api/agent/uninstall/result",
            "_previous_post": lambda handler: handler.send_error(404),
            "legacy": SimpleNamespace(
                DATABASE_FILE=self.db_path,
                dashboard_repository=lambda _path: SimpleNamespace(
                    backend=fixture.backend),
            ),
            "dispatch_heartbeat": dispatch_heartbeat,
            "dispatch_fence_observation": dispatch_fence_observation,
            "dispatch_enroll": lambda *_args, **_kw: self.fail(
                "unexpected controller enrollment"),
            "dispatch_uninstall_result": lambda *_args, **_kw: self.fail(
                "unexpected uninstall result"),
        }
        exec(route_code, namespace)
        actual_post = namespace["integrated_post"]

        class ActualRouteHandler(BaseHTTPRequestHandler):
            do_POST = actual_post

            def log_message(self, *_args):
                pass

            def read_json_body(self):
                size = int(self.headers.get("Content-Length", "-1"))
                if not 0 <= size <= 8192:
                    raise ValueError("invalid payload size")
                try:
                    return json.loads(self.rfile.read(size))
                except (ValueError, UnicodeDecodeError) as exc:
                    raise ValueError("invalid payload") from exc

            def send_json(self, status, payload):
                body = json.dumps(payload, sort_keys=True).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        def start_actual_route():
            self.server = ThreadingHTTPServer(("127.0.0.1", 0), ActualRouteHandler)
            self.server.daemon_threads = True
            self.thread = threading.Thread(
                target=self.server.serve_forever, daemon=True)
            self.thread.start()
            self.url = "http://127.0.0.1:%d/api/agent/heartbeat" % self.server.server_port

        start_actual_route()
        first = build_probe(self.agent_id)
        code, body = self._request(
            self._payload(no_drain_compatibility_probe=first))
        self.assertEqual(code, 200, body)
        self.assertTrue(verify_offer(
            first, body["no_drain_compatibility_offer"])["wire_compatible"])
        self.assertFalse(body["no_drain_compatibility_offer"]["live_no_drain_authorized"])
        self.assertEqual(body["health_status"], "online")

        # Authentication must be enforced by the real dispatcher even when
        # requests entered through the actual integrated_post route.
        bad_status, rejected = self._request(
            self._payload(no_drain_compatibility_probe=first),
            secret="bad-credential",
        )
        self.assertEqual(bad_status, 401, rejected)
        self.assertNotIn("no_drain_compatibility_offer", rejected)

        self._stop_http()
        self.backend.close()
        self.backend = create_backend(
            DatabaseConfig(driver="sqlite", database=str(self.db_path)))
        start_actual_route()
        second = build_probe(self.agent_id)
        self.assertNotEqual(first["request_id"], second["request_id"])
        code, body = self._request(
            self._payload(no_drain_compatibility_probe=second))
        self.assertEqual(code, 200, body)
        self.assertTrue(verify_offer(
            second, body["no_drain_compatibility_offer"])["wire_compatible"])
        self.assertFalse(verify_offer(
            first, body["no_drain_compatibility_offer"])["wire_compatible"])
        self.assertFalse(body["no_drain_compatibility_offer"]["live_no_drain_authorized"])
        with sqlite3.connect(self.db_path) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM agent_runtime_inventory WHERE agent_id=?",
                (self.agent_id,)
            ).fetchone()[0]
        self.assertEqual(count, 1)

        # The same real Controller route must handle a strictly read-only
        # request under a matching root-owned transaction marker. No
        # AgentPairingRepository last_used_at or runtime inventory writes.
        import time
        from unittest.mock import patch
        from game_uptime_remote_fence_evidence import CONTRACT
        when = int(time.time())
        hold = {
            "active": True, "reason": "root_owned_maintenance_hold",
            "transaction_id": "a" * 32,
            "issued_at": when - 10, "expires_at": when + 80,
        }
        evidence = {
            "kind": "CapivaraNoDrainFenceEvidence",
            "schema_version": 1,
            "agent_id": self.agent_id,
            "request_id": "b" * 32,
            "transaction_id": hold["transaction_id"],
            "issued_at": hold["issued_at"],
            "expires_at": hold["expires_at"],
            "observed_at": when,
            "contract": dict(CONTRACT),
            "agent_workers_fenced": False,
            "external_jobs_verified": False,
            "live_no_drain_authorized": False,
        }
        with sqlite3.connect(self.db_path) as connection:
            before_used = connection.execute(
                "SELECT last_used_at FROM agent_credentials WHERE id=?",
                (self.identity.credential_id,),
            ).fetchone()[0]
        self.url = "http://127.0.0.1:%d/api/agent/no-drain/observe" % self.server.server_port
        with patch("game_uptime_remote_fence_evidence.observe",
                   return_value=hold):
            code, received = self._request({
                "no_drain_fence_evidence": evidence,
            })
            self.assertEqual(code, 200, received)
            self.assertEqual(
                received["no_drain_fence_receipt"]["status"],
                "authenticated_evidence_received_unfenced",
            )
            self.assertFalse(received["remote_agent_quiescence_acked"])
            self.assertFalse(received["live_no_drain_authorized"])
            code, denied = self._request(
                {"no_drain_fence_evidence": evidence}, secret="bad-secret")
            self.assertEqual(code, 401, denied)
            self.assertNotIn("no_drain_fence_receipt", denied)
            code, denied = self._request({
                "no_drain_fence_evidence": evidence,
                "console_command": {"command": "restart"},
            })
            self.assertEqual(code, 400, denied)
        with sqlite3.connect(self.db_path) as connection:
            after_used = connection.execute(
                "SELECT last_used_at FROM agent_credentials WHERE id=?",
                (self.identity.credential_id,),
            ).fetchone()[0]
            after_count = connection.execute(
                "SELECT COUNT(*) FROM agent_runtime_inventory WHERE agent_id=?",
                (self.agent_id,),
            ).fetchone()[0]
        self.assertEqual(before_used, after_used)
        self.assertEqual(after_count, 1)


    def test_controller_hold_blocks_agent_mutation_entries_without_database_writes(self):
        """One grouped #928 regression: real HTTP/SQLite plus other dispatchers.

        A held Controller must never admit a *new* heartbeat, enrollment or
        uninstall result, but the normal heartbeat stays compatible after the
        hold is absent. This does not prove in-flight work is drained.
        """
        from unittest.mock import patch

        code, initial = self._request(self._payload())
        self.assertEqual(code, 200, initial)
        with sqlite3.connect(self.db_path) as db:
            before = db.execute(
                "SELECT last_used_at FROM agent_credentials WHERE id=?",
                (self.identity.credential_id,),
            ).fetchone()
            inventory = db.execute(
                "SELECT COUNT(*) FROM agent_runtime_inventory WHERE agent_id=?",
                (self.agent_id,),
            ).fetchone()

        denied_cases = [
            {"active": True, "reason": "root_owned_maintenance_hold"},
            {"active": True, "reason": "hold_expired_requires_operator"},
            {"active": True, "reason": "pending_journal_requires_operator_recovery"},
        ]
        for observed in denied_cases:
            with self.subTest(observed=observed), \
                 patch("agent_remote_http.observe_no_drain_hold",
                       return_value=observed), \
                 patch("agent_remote_http.enroll_remote_agent",
                       side_effect=AssertionError("enroll called while held")), \
                 patch("agent_remote_http.AgentPairingRepository",
                       side_effect=AssertionError("credential write while held")):
                code, response = self._request(self._payload())
                self.assertEqual(code, 423, response)
                self.assertEqual(response["reason"],
                                 "controller_maintenance_hold_active")
                self.assertFalse(response["remote_agent_quiescence_acked"])
                self.assertFalse(response["live_no_drain_authorized"])
                for name, (status, body) in (
                    ("enroll", dispatch_enroll({"pairing_token": "test"},
                                               backend=self.backend)),
                    ("uninstall", dispatch_uninstall_result(
                        {"status": "completed"}, headers={}, backend=self.backend)),
                ):
                    with self.subTest(endpoint=name):
                        self.assertEqual(status, 423, body)
                        self.assertFalse(body["live_no_drain_authorized"])

        with patch("agent_remote_http.observe_no_drain_hold",
                   side_effect=OSError("unreadable hold")):
            code, response = self._request(self._payload())
            self.assertEqual(code, 423, response)

        with sqlite3.connect(self.db_path) as db:
            self.assertEqual(before, db.execute(
                "SELECT last_used_at FROM agent_credentials WHERE id=?",
                (self.identity.credential_id,),
            ).fetchone())
            self.assertEqual(inventory, db.execute(
                "SELECT COUNT(*) FROM agent_runtime_inventory WHERE agent_id=?",
                (self.agent_id,),
            ).fetchone())

        with patch("agent_remote_http.observe_no_drain_hold",
                   return_value={"active": False, "reason": "hold_absent"}):
            code, resumed = self._request(self._payload())
            self.assertEqual(code, 200, resumed)
            self.assertEqual(resumed["health_status"], "online")


    def test_three_controller_agent_mutations_are_counted_until_all_exit(self):
        """Grouped concurrency and exception proof; never an update ACK.

        Count one real invocation of each dispatcher while its maintenance
        guard is still executing. Count must remain nonzero while in-flight,
        and must return to zero on every exit.
        """
        from unittest.mock import patch

        gate_barrier = threading.Barrier(4)
        release = threading.Event()
        completed = []
        errors = []
        denied = (423, {
            "status": "blocked",
            "reason": "controller_maintenance_hold_active",
            "remote_agent_quiescence_acked": False,
            "live_no_drain_authorized": False,
        })

        def suspended_guard():
            gate_barrier.wait(timeout=12)
            if not release.wait(timeout=12):
                raise AssertionError("inflight test release was not signalled")
            return denied

        calls = (
            lambda: dispatch_enroll({"pairing_token": "not-used"}, backend=self.backend),
            lambda: dispatch_heartbeat(self._payload(), headers={}, backend=self.backend),
            lambda: dispatch_uninstall_result(
                {"status": "completed"}, headers={}, backend=self.backend),
        )

        def run(call):
            try:
                completed.append(call())
            except BaseException as exc:
                errors.append(exc)

        before = observe_controller_agent_inflight()
        self.assertEqual(before["inflight_total"], 0)
        threads = [threading.Thread(target=run, args=(call,), daemon=True)
                   for call in calls]
        try:
            with patch("agent_remote_http._mutating_agent_api_hold_response",
                       side_effect=suspended_guard):
                for thread in threads:
                    thread.start()
                gate_barrier.wait(timeout=12)
                while_running = observe_controller_agent_inflight()
                self.assertEqual(while_running["inflight_total"], 3)
                self.assertEqual(while_running["inflight"], {
                    "enroll": 1, "heartbeat": 1, "uninstall_result": 1,
                })
                self.assertFalse(while_running["controller_http_acked"])
                self.assertFalse(while_running["live_no_drain_authorized"])
                self.assertEqual(while_running["scope"],
                                 "three_agent_http_dispatchers_in_this_pid_only")
        finally:
            release.set()
            for thread in threads:
                thread.join(timeout=12)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(completed, [denied] * 3)
        after = observe_controller_agent_inflight()
        self.assertEqual(after["inflight_total"], 0)
        self.assertEqual(after["generation"], before["generation"] + 6)
        self.assertFalse(after["controller_http_acked"])
        self.assertFalse(after["remote_agents_acked"])
        self.assertFalse(after["external_jobs_acked"])
        self.assertFalse(after["live_no_drain_authorized"])

        # An already-admitted mutation remains counted *after* its hold
        # check has passed. A new request may be rejected while the older
        # request is still inside the business operation.
        admitted = threading.Event()
        proceed = threading.Event()
        completed.clear()
        errors.clear()

        def suspended_enrollment(*_args, **_kwargs):
            admitted.set()
            if not proceed.wait(timeout=12):
                raise AssertionError("enrollment test release was not signalled")
            raise ValueError("synthetic rejected enrollment")

        def enrollment_call():
            return dispatch_enroll({"pairing_token": "test"}, backend=self.backend)

        worker = threading.Thread(target=run, args=(enrollment_call,), daemon=True)
        try:
            with patch("agent_remote_http._mutating_agent_api_hold_response",
                       return_value=None), \
                 patch("agent_remote_http.enroll_remote_agent",
                       side_effect=suspended_enrollment):
                worker.start()
                self.assertTrue(admitted.wait(timeout=12))
                active = observe_controller_agent_inflight()
                self.assertEqual(active["inflight_total"], 1)
                self.assertEqual(active["inflight"]["enroll"], 1)
                with patch("agent_remote_http._mutating_agent_api_hold_response",
                           return_value=denied):
                    self.assertEqual(
                        dispatch_heartbeat(self._payload(), headers={},
                                           backend=self.backend),
                        denied)
                self.assertEqual(
                    observe_controller_agent_inflight()["inflight_total"], 1)
        finally:
            proceed.set()
            worker.join(timeout=12)

        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0][0], 409)
        self.assertEqual(observe_controller_agent_inflight()["inflight_total"], 0)

        with patch("agent_remote_http._mutating_agent_api_hold_response",
                   side_effect=RuntimeError("synthetic read error")):
            with self.assertRaises(RuntimeError):
                dispatch_heartbeat(self._payload(), headers={}, backend=self.backend)
        self.assertEqual(observe_controller_agent_inflight()["inflight_total"], 0)


    def test_controller_http_interprocess_flock_is_real_and_opt_in(self):
        """Grouped: cross-process exclusion, request lifetime and fail closed.

        Only temporary storage and subprocesses. Does not enable the optional
        fence in a running Controller or turn a local lock into an ACK.
        """
        import os
        import subprocess
        from unittest.mock import patch
        import game_uptime_controller_http_inflight as tracker

        uid, gid = os.geteuid(), os.getegid()
        folder = Path(self.temp.name) / "controller-http-root"
        folder.mkdir(mode=0o755)
        witness = folder / "controller-agent-http.lock"
        denied = (423, {
            "status": "blocked",
            "reason": "controller_maintenance_hold_active",
            "remote_agent_quiescence_acked": False,
            "live_no_drain_authorized": False,
        })

        provision_controller_agent_http_lock(uid, gid, path=witness,
                                              parent_uid=uid)
        original_inode = witness.stat().st_ino
        provision_controller_agent_http_lock(uid, gid, path=witness,
                                              parent_uid=uid)
        self.assertEqual(witness.stat().st_ino, original_inode)
        self.assertEqual(witness.stat().st_mode & 0o777, 0o600)

        def shared():
            return shared_controller_agent_http_lock(
                lock_path=witness, expected_uid=uid, expected_gid=gid,
                parent_uid=uid, enabled=True)

        def exclusive():
            return exclusive_controller_agent_http_lock(
                lock_path=witness, expected_uid=uid, expected_gid=gid,
                parent_uid=uid)

        # Another actual Python PID tries to acquire the exclusive witness.
        code = (
            "import sys\\n"
            "from pathlib import Path\\n"
            "sys.path.insert(0, sys.argv[2])\\n"
            "from game_uptime_controller_agent_http_flock import "
            "exclusive_controller_agent_http_lock, ControllerHttpLockUnavailable\\n"
            "try:\\n"
            "  with exclusive_controller_agent_http_lock("
            "lock_path=Path(sys.argv[1]), expected_uid=int(sys.argv[3]), "
            "expected_gid=int(sys.argv[4]), parent_uid=int(sys.argv[3])) as state:\\n"
            "    print('ACQUIRED:' + str(state['live_no_drain_authorized']))\\n"
            "except ControllerHttpLockUnavailable:\\n"
            "  print('BLOCKED')\\n"
        )

        def child_probe():
            run = subprocess.run(
                [sys.executable, "-c", code, str(witness),
                 str(ROOT / "dashboard"), str(uid), str(gid)],
                capture_output=True, text=True, check=True, timeout=12)
            return run.stdout.strip()

        with shared():
            self.assertEqual(child_probe(), "BLOCKED")
        self.assertEqual(child_probe(), "ACQUIRED:False")

        admitted = threading.Event()
        release = threading.Event()
        result = []
        errors = []

        def pending_dispatch():
            try:
                result.append(dispatch_heartbeat(
                    self._payload(), headers={}, backend=self.backend))
            except BaseException as exc:
                errors.append(exc)

        def held_admission():
            admitted.set()
            if not release.wait(timeout=12):
                raise AssertionError("synthetic HTTP mutation timeout")
            return denied

        with patch.object(tracker, "shared_controller_agent_http_lock",
                          side_effect=shared), \\
             patch("agent_remote_http._mutating_agent_api_hold_response",
                   side_effect=held_admission):
            worker = threading.Thread(target=pending_dispatch, daemon=True)
            try:
                worker.start()
                self.assertTrue(admitted.wait(timeout=12))
                self.assertEqual(
                    observe_controller_agent_inflight()["inflight_total"], 1)
                self.assertEqual(child_probe(), "BLOCKED")
            finally:
                release.set()
                worker.join(timeout=12)
            self.assertFalse(worker.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(result, [denied])
            self.assertEqual(child_probe(), "ACQUIRED:False")

        # Exclusive coordinator occupancy prevents new request admission,
        # even with the original business hold reader mocked as absent.
        with patch.object(tracker, "shared_controller_agent_http_lock",
                          side_effect=shared), \\
             patch("agent_remote_http._mutating_agent_api_hold_response",
                   side_effect=AssertionError("should not reach hold gate")):
            with exclusive() as evidence:
                self.assertFalse(evidence["controller_http_acked"])
                self.assertFalse(evidence["live_no_drain_authorized"])
                status, response = dispatch_heartbeat(
                    self._payload(), headers={}, backend=self.backend)
                self.assertEqual(status, 423, response)
                self.assertEqual(response["reason"],
                                 "controller_http_interprocess_fence_unavailable")
            witness.chmod(0o666)
            try:
                status, response = dispatch_heartbeat(
                    self._payload(), headers={}, backend=self.backend)
                self.assertEqual(status, 423, response)
            finally:
                witness.chmod(0o600)
        self.assertEqual(observe_controller_agent_inflight()["inflight_total"], 0)


if __name__ == "__main__":
    unittest.main()
