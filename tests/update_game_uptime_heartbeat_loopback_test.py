"""Loopback HTTP -> authenticated Controller heartbeat -> Agent diagnostic.

All credentials, persistence and device state are mocked. Transport uses a real
127.0.0.1 ephemeral HTTP listener; no installed DSM or game services accessed.
"""
from __future__ import annotations

from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / "dashboard", ROOT / "database", ROOT / "core",
                  ROOT / "agents/linux/runtime", ROOT / "tests"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from agent_remote_http import dispatch_heartbeat
from agent_pairing_repository import AgentCredentialInvalid
from game_uptime_agent_wire import build_probe, verify_offer


class LoopbackHeartbeatTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        for name in ("_attach_uninstall_state", "_attach_update_state",
                     "_attach_provisioning_state", "_attach_game_data_state",
                     "_attach_instance_state", "_attach_doctor_state",
                     "_reconcile_link_incident", "_attach_backup_clone_state"):
            stack.enter_context(patch("agent_remote_http." + name))
        auth = stack.enter_context(patch("agent_remote_http.AgentPairingRepository"))
        self.auth = auth.return_value.authenticate

        def authenticate(*, credential_id, credential_secret, fingerprint):
            if (credential_id, credential_secret, fingerprint) != (
                    "fixture-credential", "fixture-secret", "fixture-fingerprint"):
                raise AgentCredentialInvalid("fixture credential rejected")
            return {"agent_id": "trusted-agent", "status": "active"}
        self.auth.side_effect = authenticate
        stack.enter_context(patch("agent_remote_http.record_agent_heartbeat",
                                  return_value={"agent_id": "trusted-agent",
                                                "health_status": "online"}))
        stack.enter_context(patch("agent_remote_http.validated_heartbeat_recovery_claims",
                                  return_value=[]))
        stack.enter_context(patch(
            "minecraft_recovery_heartbeat_claims.owned_instance_ids_for_agent",
            return_value=set()))

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                return

            def do_POST(self):
                if self.path != "/api/agent/heartbeat":
                    self.send_error(404)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "-1"))
                    if not (0 <= length <= 4096):
                        self.send_error(413)
                        return
                    body = json.loads(self.rfile.read(length))
                except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
                    self.send_error(400)
                    return
                code, result = dispatch_heartbeat(
                    body, headers=self.headers, backend=object())
                encoded = json.dumps(result, sort_keys=True).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.addCleanup(self.server.server_close)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop)
        self.url = "http://127.0.0.1:%d/api/agent/heartbeat" % self.server.server_port

    def _stop(self):
        self.server.shutdown()
        self.thread.join(timeout=3)

    def post(self, body, *, secret="fixture-secret"):
        request = Request(
            self.url,
            data=json.dumps(body, sort_keys=True).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "X-Capivara-Agent-Credential": "fixture-credential",
                     "X-Capivara-Agent-Secret": secret,
                     "X-Capivara-Agent-Fingerprint": "fixture-fingerprint"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=4) as response:
                return response.status, json.loads(response.read())
        except HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_matching_authenticated_exchange_remains_diagnostic(self):
        probe = build_probe("trusted-agent")
        code, response = self.post({"agent_id": "untrusted-body",
                                    "no_drain_compatibility_probe": probe})
        self.assertEqual(code, 200)
        offer = response["no_drain_compatibility_offer"]
        self.assertEqual(offer["status"], "wire_compatible")
        self.assertTrue(verify_offer(probe, offer)["wire_compatible"])
        self.assertFalse(offer["live_no_drain_authorized"])
        self.assertNotIn("update", offer)
        self.assertNotIn("instance_command", offer)
        self.auth.assert_called_once()

    def test_credential_failure_does_not_leak_offer(self):
        probe = build_probe("trusted-agent")
        code, response = self.post(
            {"no_drain_compatibility_probe": probe}, secret="wrong-secret")
        self.assertEqual(code, 401)
        self.assertNotIn("no_drain_compatibility_offer", response)

    def test_contract_divergence_blocks_but_preserves_heartbeat(self):
        probe = build_probe("trusted-agent")
        probe["contract"]["protocol"] = "unsupported"
        code, response = self.post({"no_drain_compatibility_probe": probe})
        self.assertEqual(code, 200)
        self.assertEqual(response["health_status"], "online")
        self.assertEqual(response["no_drain_compatibility_offer"]["status"], "blocked")

    def test_spoofed_agent_is_bound_to_authenticated_agent(self):
        probe = build_probe("different-agent")
        code, response = self.post({"agent_id": "different-agent",
                                    "no_drain_compatibility_probe": probe})
        self.assertEqual(code, 200)
        self.assertEqual(response["no_drain_compatibility_offer"]["status"], "blocked")
        self.assertEqual(response["no_drain_compatibility_offer"]["agent_id"], "trusted-agent")

    def test_absent_probe_preserves_legacy_heartbeat(self):
        code, response = self.post({"agent_id": "trusted-agent"})
        self.assertEqual(code, 200)
        self.assertEqual(response["health_status"], "online")
        self.assertNotIn("no_drain_compatibility_offer", response)

    def test_response_is_bound_to_exact_request_nonce(self):
        original = build_probe("trusted-agent")
        code, response = self.post({"no_drain_compatibility_probe": original})
        self.assertEqual(code, 200)
        self.assertFalse(verify_offer(build_probe("trusted-agent"),
                                      response["no_drain_compatibility_offer"])["wire_compatible"])


if __name__ == "__main__":
    unittest.main()
