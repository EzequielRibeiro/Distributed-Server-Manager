"""Real loopback HTTP Agent -> Controller Server Pack outbox with isolated DB.

The transport uses a bound ephemeral 127.0.0.1 listener. All Controller records
live in the disposable SQLite fixture, with feature opt-in limited to this test.
No production service, storage path or game process is accessed.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from tests.minecraft_serverpack_outbox_transport_e2e_test import ServerPackOutboxTransportE2E
from minecraft_serverpack_report_outbox import (
    read_serverpack_report_delivery,
    acknowledge_serverpack_report_delivery,
)
from agent_pairing_repository import AgentCredentialInvalid


class ServerPackLoopbackHttpE2E(ServerPackOutboxTransportE2E):
    def setUp(self):
        super().setUp()
        backend = self.fixture.fixture.backend

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                if self.path != "/api/agent/heartbeat":
                    self.send_error(404)
                    return
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if size < 0 or size > 128_000:
                        self.send_error(413)
                        return
                    body = json.loads(self.rfile.read(size))
                except (ValueError, TypeError):
                    self.send_error(400)
                    return
                from agent_remote_http import dispatch_heartbeat
                status, result = dispatch_heartbeat(
                    body, headers=self.headers, backend=backend
                )
                response = json.dumps(result).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.worker.join, 2)
        self.addCleanup(self.server.shutdown)

    def http_request(self, payload, *, headers=None):
        url = f"http://127.0.0.1:{self.server.server_port}/api/agent/heartbeat"
        request = Request(
            url,
            data=json.dumps(payload).encode(),
            method="POST",
            headers={
                **self.headers,
                **(headers or {}),
                "Content-Type": "application/json",
            },
        )
        with urlopen(request, timeout=12) as response:
            return response.status, json.loads(response.read())

    def roundtrip(self, authenticated_agent=None):
        pending = read_serverpack_report_delivery(self.directory)
        self.assertIsNotNone(pending)
        payload, filename = pending
        if authenticated_agent is not None:
            from agent_remote_http import AgentPairingRepository
            AgentPairingRepository.return_value.authenticate.return_value = {
                "agent_id": authenticated_agent,
                "status": "active",
            }
        status, response = self.http_request({"serverpack_report_delivery": payload})
        self.assertEqual(status, 200)
        return payload, filename, response["serverpack_report_delivery"]

    def test_invalid_agent_credential_rejected_before_publication_http(self):
        from agent_remote_http import AgentPairingRepository
        AgentPairingRepository.return_value.authenticate.side_effect = AgentCredentialInvalid()
        with self.assertRaises(HTTPError) as error:
            self.http_request({"serverpack_report_delivery": read_serverpack_report_delivery(self.directory)[0]},
                headers={"X-Capivara-Agent-Secret": "invalid-secret"})
        self.assertEqual(error.exception.code, 401)
        self.assertEqual(self.fixture.count(), 0)
        self.assertIsNotNone(read_serverpack_report_delivery(self.directory))

    def test_successful_http_ack_and_replay_no_duplicate_rows(self):
        sent, filename, first = self.roundtrip()
        self.assertEqual(first["status"], "published")
        self.assertEqual(self.fixture.count(), 2)
        _, _, replay = self.roundtrip()
        self.assertEqual(replay["status"], "published")
        self.assertEqual(self.fixture.count(), 2)
        self.assertTrue(acknowledge_serverpack_report_delivery(self.directory, filename, sent, replay))
        self.assertIsNone(read_serverpack_report_delivery(self.directory))

    def test_mismatched_authenticated_agent_cannot_publish_http(self):
        sent, filename, response = self.roundtrip(authenticated_agent="other-agent")
        self.assertEqual(response["status"], "rejected")
        self.assertEqual(self.fixture.count(), 0)
        self.assertFalse(acknowledge_serverpack_report_delivery(self.directory, filename, sent, response))
        self.assertIsNotNone(read_serverpack_report_delivery(self.directory))

    def test_corrupted_report_batch_rejected_without_partial_state_http(self):
        pending = read_serverpack_report_delivery(self.directory)
        altered = dict(pending[0])
        altered["reports"] = altered["reports"][:-1]
        status, response = self.http_request({"serverpack_report_delivery": altered})
        self.assertEqual(status, 200)
        self.assertEqual(response["serverpack_report_delivery"]["status"], "rejected")
        self.assertEqual(self.fixture.count(), 0)
        self.assertIsNotNone(read_serverpack_report_delivery(self.directory))
