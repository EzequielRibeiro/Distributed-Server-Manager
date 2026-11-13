"""#928 authenticated, read-only Agent/Controller compatibility exchange.

All fixtures mock heartbeat persistence and credentials. No live DSM services,
updates, database or game processes are touched.
"""
from __future__ import annotations
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from contextlib import ExitStack
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT/"dashboard", ROOT/"database", ROOT/"core"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))


def _load(name, path):
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


agent_wire = _load("dsm928_agent_wire", ROOT/"agents/linux/runtime/game_uptime_agent_wire.py")
controller_wire = _load("dsm928_controller_wire", ROOT/"dashboard/game_uptime_heartbeat_compat.py")
from agent_remote_http import dispatch_heartbeat


class WireContractTests(unittest.TestCase):
    def test_same_readonly_contract_both_ends(self):
        self.assertEqual(agent_wire.WIRE_CONTRACT, controller_wire.WIRE_CONTRACT)
        probe = agent_wire.build_probe("agent-A")
        offer = controller_wire.assess_authenticated_probe(
            probe, authenticated_agent_id="agent-A")
        result = agent_wire.verify_offer(probe, offer)
        self.assertTrue(result["wire_compatible"])
        self.assertFalse(result["live_no_drain_authorized"])
        self.assertFalse(offer["live_no_drain_authorized"])

    def test_spoofed_identity_rejected(self):
        probe = agent_wire.build_probe("agent-imposter")
        offer = controller_wire.assess_authenticated_probe(
            probe, authenticated_agent_id="agent-trusted")
        self.assertEqual(offer["status"], "blocked")
        self.assertFalse(agent_wire.verify_offer(probe, offer)["wire_compatible"])
        self.assertEqual(offer["agent_id"], "agent-trusted")

    def test_mismatched_schema_rejected(self):
        probe = agent_wire.build_probe("agent-trusted")
        probe["contract"]["schema"] = "2"
        offer = controller_wire.assess_authenticated_probe(
            probe, authenticated_agent_id="agent-trusted")
        self.assertEqual(offer["status"], "blocked")
        self.assertFalse(agent_wire.verify_offer(probe, offer)["wire_compatible"])

    def test_replayed_nonce_rejected(self):
        probe = agent_wire.build_probe("agent-trusted")
        offer = controller_wire.assess_authenticated_probe(
            probe, authenticated_agent_id="agent-trusted")
        fresh = agent_wire.build_probe("agent-trusted")
        self.assertNotEqual(fresh["request_id"], probe["request_id"])
        self.assertFalse(agent_wire.verify_offer(fresh, offer)["wire_compatible"])

    def test_unknown_or_malicious_offer_never_authorizes(self):
        probe = agent_wire.build_probe("agent-trusted")
        self.assertFalse(agent_wire.verify_offer(probe, None)["wire_compatible"])
        offer = controller_wire.assess_authenticated_probe(
            probe, authenticated_agent_id="agent-trusted")
        offer["live_no_drain_authorized"] = True
        self.assertFalse(agent_wire.verify_offer(probe, offer)["wire_compatible"])

    def test_missing_nonce_fails_closed(self):
        probe = agent_wire.build_probe("agent-trusted")
        probe["request_id"] = "invalid"
        offer = controller_wire.assess_authenticated_probe(
            probe, authenticated_agent_id="agent-trusted")
        self.assertEqual(offer["status"], "blocked")
        self.assertFalse(agent_wire.verify_offer(probe, offer)["wire_compatible"])


class AuthenticatedHeartbeatBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in (
            "_attach_uninstall_state", "_attach_update_state",
            "_attach_provisioning_state", "_attach_game_data_state",
            "_attach_instance_state", "_attach_doctor_state",
            "_reconcile_link_incident", "_attach_backup_clone_state",
        ):
            self.stack.enter_context(patch("agent_remote_http." + name))
        self.auth = self.stack.enter_context(patch("agent_remote_http.AgentPairingRepository"))
        self.auth.return_value.authenticate.return_value = {
            "agent_id": "trusted-agent", "status": "active"}
        self.stack.enter_context(patch("agent_remote_http.record_agent_heartbeat",
                     return_value={"agent_id": "trusted-agent", "health_status": "online"}))
        self.stack.enter_context(patch("agent_remote_http.validated_heartbeat_recovery_claims",
                                       return_value=[]))
        self.stack.enter_context(patch(
            "minecraft_recovery_heartbeat_claims.owned_instance_ids_for_agent",
            return_value=set()))
        self.headers = {
            "X-Capivara-Agent-Credential": "test-credential",
            "X-Capivara-Agent-Secret": "test-secret",
            "X-Capivara-Agent-Fingerprint": "test-fingerprint",
        }

    def post(self, payload):
        return dispatch_heartbeat(payload, headers=self.headers, backend=object())

    def test_authenticated_roundtrip_and_bounded_no_draining(self):
        probe = agent_wire.build_probe("trusted-agent")
        status, data = self.post({"agent_id": "payload-spoof",
                                  "no_drain_compatibility_probe": probe})
        self.assertEqual(status, 200)
        offer = data["no_drain_compatibility_offer"]
        self.assertEqual(offer["agent_id"], "trusted-agent")
        self.assertEqual(offer["status"], "wire_compatible")
        self.assertTrue(agent_wire.verify_offer(probe, offer)["wire_compatible"])
        self.assertFalse(offer["live_no_drain_authorized"])
        self.assertNotIn("game_commands", offer)
        self.assertNotIn("update", offer)

    def test_spoofed_probe_identity_blocked_after_auth(self):
        probe = agent_wire.build_probe("imposter-agent")
        status, data = self.post({"no_drain_compatibility_probe": probe})
        self.assertEqual(status, 200)
        self.assertEqual(data["no_drain_compatibility_offer"]["status"], "blocked")
        self.assertEqual(data["no_drain_compatibility_offer"]["agent_id"], "trusted-agent")

    def test_absent_probe_preserves_old_heartbeat(self):
        status, data = self.post({"agent_id": "trusted-agent"})
        self.assertEqual(status, 200)
        self.assertEqual(data["health_status"], "online")
        self.assertNotIn("no_drain_compatibility_offer", data)

    def test_invalid_auth_never_receives_offer(self):
        from agent_pairing_repository import AgentCredentialInvalid
        self.auth.return_value.authenticate.side_effect = AgentCredentialInvalid("bad")
        probe = agent_wire.build_probe("trusted-agent")
        status, data = self.post({"no_drain_compatibility_probe": probe})
        self.assertEqual(status, 401)
        self.assertNotIn("no_drain_compatibility_offer", data)


if __name__ == "__main__":
    unittest.main()
