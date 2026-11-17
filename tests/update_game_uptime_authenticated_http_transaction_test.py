"""#928: real credentialed Controller HTTP receipt gates an isolated /tmp transaction.

Combines the existing real SQLite pairing/authentication and heartbeat dispatcher
with the disposable supervisor/PID verification test. No live Controller, Agent,
systemd or game services are accessed; no production authorization is possible.
"""
from __future__ import annotations

import unittest

from update_game_uptime_sqlite_http_integration_test import (
    ActualDispatcherSqliteHttpTests,
)
from update_game_uptime_evidence_rehearsal_test import (
    ObservedEvidenceFixtureTests,
)
from update_game_uptime_evidence_rehearsal_test import observed


class CredentialedTransportRehearsalTests(unittest.TestCase):
    def setUp(self):
        self.controller = ActualDispatcherSqliteHttpTests(
            methodName="test_credentialed_sqlite_controller_survives_restart_and_new_nonce")
        self.controller.fixture_agent_id = "fixture-agent"
        self.controller.setUp()
        self.addCleanup(self.controller.doCleanups)

        self.rehearsal = ObservedEvidenceFixtureTests(
            methodName="test_matching_observation_composes_transaction_but_never_authorizes")
        self.rehearsal.setUp()
        self.addCleanup(self.rehearsal.doCleanups)
        self.assertEqual(self.controller.agent_id, self.rehearsal.probe["agent_id"])

    def send_probe(self, probe, *, secret=None):
        return self.controller._request(
            self.controller._payload(no_drain_compatibility_probe=probe),
            secret=secret,
        )

    def use_credentialed_offer(self, probe, offer):
        self.rehearsal.probe = probe
        self.rehearsal.offer = offer

    def test_real_authenticated_sqlite_http_offer_precedes_disposable_apply(self):
        probe = observed._AGENT.build_probe(self.controller.agent_id)
        code, response = self.send_probe(probe)
        self.assertEqual(code, 200, response)
        self.assertEqual(response["status"], "active")
        offer = response["no_drain_compatibility_offer"]
        self.assertTrue(observed._AGENT.verify_offer(probe, offer)["wire_compatible"])
        self.use_credentialed_offer(probe, offer)

        result = self.rehearsal.execute()
        self.assertEqual(result["status"], "verified")
        self.assertTrue(result["heartbeat_envelope_compatible"])
        self.assertTrue(result["pinned_supervisor_observed"])
        self.assertFalse(result["live_no_drain_authorized"])
        self.assertEqual(self.rehearsal.fixture.states[
            "dsm928-e2e-minecraft-pinned.service"]["pid"], 22001)
        self.assertEqual(self.rehearsal.fixture.states[
            "dsm928-e2e-dayz-sim.service"]["pid"], 22002)

    def test_invalid_credential_never_generates_offer_or_snapshot(self):
        probe = observed._AGENT.build_probe(self.controller.agent_id)
        code, response = self.send_probe(probe, secret="wrong-isolated-secret")
        self.assertEqual(code, 401)
        self.assertNotIn("no_drain_compatibility_offer", response)
        with self.assertRaisesRegex(observed.EvidenceSafetyError, "heartbeat"):
            self.rehearsal.execute(heartbeat_probe=probe, heartbeat_offer={})
        self.rehearsal.assert_no_mutation()

    def test_mismatched_agent_probed_over_actual_http_blocks_transaction(self):
        probe = observed._AGENT.build_probe("fixture-other")
        code, response = self.send_probe(probe)
        self.assertEqual(code, 200, response)
        offer = response["no_drain_compatibility_offer"]
        self.assertEqual(offer["status"], "blocked")
        self.assertEqual(offer["agent_id"], self.controller.agent_id)
        with self.assertRaisesRegex(observed.EvidenceSafetyError, "heartbeat"):
            self.rehearsal.execute(heartbeat_probe=probe, heartbeat_offer=offer)
        self.rehearsal.assert_no_mutation()

    def test_controller_restart_invalidates_old_offer_for_fresh_probe(self):
        first = observed._AGENT.build_probe(self.controller.agent_id)
        code, response = self.send_probe(first)
        self.assertEqual(code, 200, response)
        stale_offer = response["no_drain_compatibility_offer"]
        self.controller._restart_controller_dispatcher()
        second = observed._AGENT.build_probe(self.controller.agent_id)
        self.assertNotEqual(first["request_id"], second["request_id"])
        with self.assertRaisesRegex(observed.EvidenceSafetyError, "heartbeat"):
            self.rehearsal.execute(
                heartbeat_probe=second, heartbeat_offer=stale_offer,
            )
        self.rehearsal.assert_no_mutation()
        code, response = self.send_probe(second)
        self.assertEqual(code, 200, response)
        self.use_credentialed_offer(second, response["no_drain_compatibility_offer"])
        result = self.rehearsal.execute()
        self.assertEqual(result["status"], "verified")
        self.assertFalse(result["live_no_drain_authorized"])

    def test_authentic_transport_cannot_override_changed_pinned_process(self):
        probe = observed._AGENT.build_probe(self.controller.agent_id)
        code, response = self.send_probe(probe)
        self.assertEqual(code, 200, response)
        self.use_credentialed_offer(probe, response["no_drain_compatibility_offer"])
        self.rehearsal.override_pinned = {"main_pid": 90090}
        with self.assertRaisesRegex(observed.EvidenceSafetyError, "process identity"):
            self.rehearsal.execute()
        self.rehearsal.assert_no_mutation()


if __name__ == "__main__":
    unittest.main()
