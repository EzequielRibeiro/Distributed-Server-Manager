"""#928 authenticated, read-only Agent/Controller compatibility exchange.

All fixtures mock heartbeat persistence and credentials. No live DSM services,
updates, database or game processes are touched.
"""
from __future__ import annotations
import ast
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
from agent_remote_http import dispatch_heartbeat, dispatch_fence_observation


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

    def test_phase2_authenticated_remote_fence_receipt_never_acks_quiescence(self):
        """One grouped end-to-end contract: auth, lease, nonce, negative proof."""
        import time
        agent_evidence = _load(
            "dsm928_agent_fence_evidence",
            ROOT / "agents/linux/runtime/game_uptime_agent_fence_evidence.py",
        )
        controller_evidence = _load(
            "dsm928_controller_fence_evidence",
            ROOT / "dashboard/game_uptime_remote_fence_evidence.py",
        )
        now = int(time.time())
        local_hold = {
            "active": True, "reason": "root_owned_maintenance_hold",
            "transaction_id": "a" * 32,
            "issued_at": now - 10, "expires_at": now + 80,
        }
        with patch.object(agent_evidence, "observe", return_value=local_hold):
            probe = agent_evidence.build_fence_evidence("trusted-agent", now=now)
        self.assertEqual(probe["transaction_id"], "a" * 32)
        self.assertFalse(probe["agent_workers_fenced"])
        self.assertFalse(probe["external_jobs_verified"])
        self.assertFalse(probe["live_no_drain_authorized"])
        with patch.object(controller_evidence, "observe",
                          return_value=local_hold), patch(
                          "agent_remote_http.receipt_for_authenticated_agent",
                          side_effect=controller_evidence.receipt_for_authenticated_agent):
            status, payload = self.post({
                "agent_id": "trusted-agent",
                "no_drain_fence_evidence": probe,
            })
            self.assertEqual(status, 200)
            receipt = payload["no_drain_fence_receipt"]
            self.assertEqual(receipt["status"],
                             "authenticated_evidence_received_unfenced")
            self.assertEqual(receipt["agent_id"], "trusted-agent")
            self.assertEqual(receipt["transaction_id"], "a" * 32)
            verified = agent_evidence.verify_fence_receipt(
                probe, receipt, now=now)
            self.assertTrue(verified["wire_receipt_verified"])
            self.assertFalse(verified["remote_agent_quiescence_acked"])
            self.assertFalse(verified["live_no_drain_authorized"])

            # A copied receipt cannot satisfy another nonce/transaction.
            with patch.object(agent_evidence, "observe",
                              return_value=local_hold):
                fresh = agent_evidence.build_fence_evidence(
                    "trusted-agent", now=now)
            self.assertNotEqual(fresh["request_id"], probe["request_id"])
            self.assertFalse(agent_evidence.verify_fence_receipt(
                fresh, receipt, now=now)["wire_receipt_verified"])
            self.assertFalse(agent_evidence.verify_fence_receipt(
                probe, receipt, now=now + 31)["wire_receipt_verified"])

            spoof = dict(probe, agent_id="other-agent")
            status, mismatched = self.post({
                "no_drain_fence_evidence": spoof,
            })
            self.assertEqual(status, 200)
            self.assertEqual(
                mismatched["no_drain_fence_receipt"]["status"], "blocked")
            self.assertEqual(
                mismatched["no_drain_fence_receipt"]["agent_id"],
                "trusted-agent",
            )
            other_tx = dict(probe, transaction_id="b" * 32)
            status, mismatched = self.post({
                "no_drain_fence_evidence": other_tx,
            })
            self.assertEqual(status, 200)
            self.assertEqual(
                mismatched["no_drain_fence_receipt"]["status"], "blocked")
            self.assertFalse(agent_evidence.verify_fence_receipt(
                other_tx, receipt, now=now)["wire_receipt_verified"])

            with patch.object(controller_evidence, "observe",
                              return_value={"active": False, "reason": "hold_absent"}):
                status, missing_hold = self.post({
                    "no_drain_fence_evidence": probe,
                })
                self.assertEqual(status, 200)
                self.assertEqual(
                    missing_hold["no_drain_fence_receipt"]["status"], "blocked")
        expired = dict(probe, observed_at=now - 40)
        self.assertEqual(controller_evidence.receipt_for_authenticated_agent(
            expired, authenticated_agent_id="trusted-agent", now=now
        )["status"], "blocked")
        with patch.object(agent_evidence, "observe",
                          return_value={"active": False, "reason": "hold_absent"}):
            self.assertIsNone(agent_evidence.build_fence_evidence(
                "trusted-agent", now=now))

        with patch.object(controller_evidence, "observe",
                          return_value=local_hold):
            from agent_pairing_repository import AgentCredentialInvalid
            self.auth.return_value.authenticate.side_effect = AgentCredentialInvalid("bad")
            status, rejected = self.post({
                "no_drain_fence_evidence": probe,
            })
            self.assertEqual(status, 401)
            self.assertNotIn("no_drain_fence_receipt", rejected)

    def test_hold_readonly_route_and_agent_transport_never_dispatch_commands(self):
        """One grouped phase-2 proof: authenticated SELECT-only endpoint.

        Exercise the real dispatcher and isolated Agent function body, not
        any production service, network, storage, or background thread.
        """
        import os
        import time
        from types import SimpleNamespace
        from game_uptime_remote_fence_evidence import (
            receipt_for_authenticated_agent,
        )
        from game_uptime_maintenance_hold import observe as hold_observe
        agent_evidence = _load(
            "dsm928_hold_agent_evidence",
            ROOT / "agents/linux/runtime/game_uptime_agent_fence_evidence.py",
        )
        now = int(time.time())
        hold = {
            "active": True, "reason": "root_owned_maintenance_hold",
            "transaction_id": "a" * 32,
            "issued_at": now - 10, "expires_at": now + 80,
        }
        with patch.object(agent_evidence, "observe", return_value=hold):
            evidence = agent_evidence.build_fence_evidence(
                "trusted-agent", now=now)
        self.assertIsNotNone(evidence)
        self.auth.return_value.authenticate_readonly.return_value = {
            "agent_id": "trusted-agent", "status": "active",
        }
        with patch("agent_remote_http.receipt_for_authenticated_agent",
                   side_effect=receipt_for_authenticated_agent), patch(
                   "game_uptime_remote_fence_evidence.observe",
                   return_value=hold), patch(
                   "agent_remote_http.record_agent_heartbeat",
                   side_effect=AssertionError("heartbeat must never run")):
            code, data = dispatch_fence_observation(
                {"no_drain_fence_evidence": evidence},
                headers=self.headers, backend=object())
            self.assertEqual(code, 200)
            self.assertEqual(set(data), {
                "no_drain_fence_receipt", "remote_agent_quiescence_acked",
                "live_no_drain_authorized"})
            receipt = data["no_drain_fence_receipt"]
            self.assertEqual(receipt["status"],
                             "authenticated_evidence_received_unfenced")
            self.assertFalse(data["remote_agent_quiescence_acked"])
            self.assertFalse(data["live_no_drain_authorized"])
            self.assertTrue(agent_evidence.verify_fence_receipt(
                evidence, receipt, now=now)["wire_receipt_verified"])
            self.auth.return_value.authenticate.assert_not_called()
            self.auth.return_value.authenticate_readonly.assert_called_once()

            for hostile in ({}, {"no_drain_fence_evidence": evidence,
                                  "console_command": {}},
                            {"no_drain_fence_evidence": evidence,
                             "result_flush": False}):
                status, rejected = dispatch_fence_observation(
                    hostile, headers=self.headers, backend=object())
                self.assertEqual(status, 400)
                self.assertFalse(rejected["live_no_drain_authorized"])

            bad = dict(evidence, agent_id="some-other-agent")
            status, rejected = dispatch_fence_observation(
                {"no_drain_fence_evidence": bad},
                headers=self.headers, backend=object())
            self.assertEqual(status, 200)
            self.assertEqual(
                rejected["no_drain_fence_receipt"]["status"], "blocked")
            with patch("game_uptime_remote_fence_evidence.observe",
                       return_value={"active": False, "reason": "hold_absent"}):
                status, rejected = dispatch_fence_observation(
                    {"no_drain_fence_evidence": evidence},
                    headers=self.headers, backend=object())
                self.assertEqual(status, 200)
                self.assertEqual(rejected["no_drain_fence_receipt"]["status"],
                                 "blocked")
            from agent_pairing_repository import AgentCredentialInvalid
            self.auth.return_value.authenticate_readonly.side_effect = (
                AgentCredentialInvalid("bad"))
            status, denied = dispatch_fence_observation(
                {"no_drain_fence_evidence": evidence},
                headers=self.headers, backend=object())
            self.assertEqual(status, 401)
            self.assertNotIn("no_drain_fence_receipt", denied)

        # Verify SQL-level SELECT-only authentication and the routing guard.
        pairing_source = (
            ROOT / "database/agent_pairing_repository.py").read_text()
        pairing_ast = ast.parse(pairing_source)
        class_node = next(n for n in pairing_ast.body
                          if isinstance(n, ast.ClassDef)
                          and n.name == "AgentPairingRepository")
        method = next(n for n in class_node.body
                      if isinstance(n, ast.FunctionDef)
                      and n.name == "authenticate_readonly")
        self.assertIn("self.backend.connect()", ast.unparse(method))
        self.assertNotIn("UPDATE agent_credentials", ast.unparse(method))
        self.assertNotIn("self.backend.transaction()", ast.unparse(method))
        route = (ROOT / "dashboard/server_part11.py").read_text()
        self.assertIn("NO_DRAIN_OBSERVE_PATH", route)
        self.assertIn("dispatch_fence_observation", route)

        # Execute only the standalone Agent function with simulated transport.
        agent_src = (ROOT / "agents/linux/runtime/agent.py").read_text()
        node = next(n for n in ast.parse(agent_src).body
                    if isinstance(n, ast.FunctionDef)
                    and n.name == "observe_remote_fence_readonly")
        invoked = {
            c.func.id for c in ast.walk(node)
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
        }
        self.assertFalse({"_inventory", "heartbeat", "_write_config",
                          "reconcile_all", "handle_command"}.intersection(invoked))
        observed = []
        def post(url, payload, headers=None):
            observed.append((url, payload, headers))
            return {"no_drain_fence_receipt": receipt}
        scope = {
            "os": os, "build_fence_evidence": lambda aid: evidence,
            "_post": post,
            "verify_fence_receipt": agent_evidence.verify_fence_receipt,
        }
        exec(compile(ast.Module(body=[node], type_ignores=[]),
                     "read_only_agent_fixture", "exec"), scope)
        config = {"agent_id": "trusted-agent",
                  "controller_url": "https://controller.example",
                  "credential_id": "credential", "credential_secret": "secret",
                  "fingerprint": "fingerprint"}
        with patch.dict(os.environ, {"DSM928_REMOTE_FENCE_DIAGNOSTIC": "1"}):
            result = scope["observe_remote_fence_readonly"](config)
        self.assertEqual(result["wire_receipt_verified"], True)
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0][0],
                         "https://controller.example/api/agent/no-drain/observe")
        self.assertEqual(set(observed[0][1]), {"no_drain_fence_evidence"})
        self.assertFalse(result["live_no_drain_authorized"])
        # Existing Agent hold loop must call only the diagnostic path.
        agent_run = next(n for n in ast.parse(agent_src).body
                         if isinstance(n, ast.FunctionDef)
                         and n.name == "run_forever")
        self.assertIn("observe_remote_fence_readonly(config)",
                      ast.unparse(agent_run))

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



class AgentHeartbeatScopeTests(unittest.TestCase):
    def test_serverpack_observation_globals_belong_to_heartbeat(self):
        """Protect the unrelated Server Pack observation path during PR sync."""
        source = (ROOT / "agents/linux/runtime/agent.py").read_text()
        functions = {
            node.name: node for node in ast.parse(source).body
            if isinstance(node, ast.FunctionDef)
        }
        self.assertIn("heartbeat", functions)
        self.assertIn("enroll", functions)
        heartbeat_globals = {
            name for node in functions["heartbeat"].body
            if isinstance(node, ast.Global)
            for name in node.names
        }
        enroll_globals = {
            name for node in functions["enroll"].body
            if isinstance(node, ast.Global)
            for name in node.names
        }
        required = {"_SERVERPACK_OBSERVATION_PENDING", "_SERVERPACK_LAST_SCANNED"}
        self.assertTrue(required.issubset(heartbeat_globals))
        self.assertFalse(required.intersection(enroll_globals))



    def test_merged_agent_location_and_no_drain_diagnostics_coexist(self):
        """Protect main's GeoIP/location fields alongside the Draft PR probe.

        This is a static regression test for integration, not proof that the
        real Controller/Agent daemons survive a release or migration.
        """
        source = (ROOT / "agents/linux/runtime/agent.py").read_text()
        syntax = ast.parse(source)
        imports = {
            alias.asname or alias.name for node in syntax.body
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        self.assertTrue({
            "observe_host_geolocation", "build_no_drain_probe",
            "verify_no_drain_offer",
        }.issubset(imports))
        functions = {
            node.name: node for node in syntax.body
            if isinstance(node, ast.FunctionDef)
        }
        self.assertIn("_inventory", functions)
        self.assertIn("heartbeat", functions)

        inventory = functions["_inventory"]
        heartbeat = functions["heartbeat"]
        inventory_calls = [
            node.func.id for node in ast.walk(inventory)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        self.assertEqual(inventory_calls.count("observe_public_ipv4"), 1)
        self.assertIn("observe_host_geolocation", inventory_calls)
        self.assertIn("build_no_drain_probe", inventory_calls)
        inventory_keys = {
            node.value for node in ast.walk(inventory)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        self.assertTrue({"geo_location_observation",
                         "no_drain_compatibility_probe"}.issubset(inventory_keys))

        heartbeat_calls = [
            node.func.id for node in ast.walk(heartbeat)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        self.assertIn("verify_no_drain_offer", heartbeat_calls)
        self.assertIn("_write_config", heartbeat_calls)
        heartbeat_keys = {
            node.value for node in ast.walk(heartbeat)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        self.assertTrue({
            "controller_location", "no_drain_compatibility_offer",
            "no_drain_compatibility_probe", "no_drain_wire_diagnostic",
        }.issubset(heartbeat_keys))
        # Reading the diagnostic must never become a command or implicit
        # consent to stop/restart/drain the live game service.
        self.assertFalse({
            "stop_games", "start_games", "restart_games", "drain_games",
        }.intersection(heartbeat_calls))


if __name__ == "__main__":
    unittest.main()
