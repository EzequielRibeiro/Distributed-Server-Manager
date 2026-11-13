"""DSM #928: real Controller dispatcher, credential DB and SQLite heartbeat E2E.

Only an ephemeral 127.0.0.1 HTTP listener and temporary SQLite file are used.
This runs the actual AgentPairingRepository, authentication and dispatch_heartbeat
on both sides of a transport restart. It does not boot the full DSM web app,
migrate a production database, alter systemd or grant no-drain permission.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

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
from agent_remote_http import dispatch_heartbeat
from game_uptime_agent_wire import build_probe, verify_offer


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
        self.agent_id = "agent-928-sqlite"
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


if __name__ == "__main__":
    unittest.main()
