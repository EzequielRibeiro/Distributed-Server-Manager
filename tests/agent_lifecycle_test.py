#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.agent_lifecycle import (
    AGENT_TRANSITIONS,
    InvalidAgentState,
    InvalidAgentTransition,
    allowed_agent_transitions,
    can_transition_agent,
    normalize_agent_state,
    transition_agent,
)
from core.placement_readiness import AGENT_STATES


class AgentLifecycleTest(unittest.TestCase):
    def test_transition_table_covers_official_states(self):
        self.assertEqual(set(AGENT_TRANSITIONS), set(AGENT_STATES))

    def test_normalization_accepts_official_state(self):
        self.assertEqual(normalize_agent_state(" ACTIVE "), "active")

    def test_unknown_state_is_rejected(self):
        with self.assertRaises(InvalidAgentState):
            normalize_agent_state("ready")

    def test_pending_can_enter_pairing(self):
        self.assertTrue(can_transition_agent("pending", "pairing"))

    def test_pairing_can_activate_agent(self):
        result = transition_agent("pairing", "active")
        self.assertEqual(result.current, "pairing")
        self.assertEqual(result.target, "active")
        self.assertTrue(result.changed)

    def test_active_can_go_offline_and_return_active(self):
        self.assertTrue(can_transition_agent("active", "offline"))
        self.assertTrue(can_transition_agent("offline", "active"))

    def test_active_cannot_jump_back_to_pairing(self):
        self.assertFalse(can_transition_agent("active", "pairing"))
        with self.assertRaises(InvalidAgentTransition):
            transition_agent("active", "pairing")

    def test_disabled_requires_pending_before_pairing_or_active(self):
        self.assertEqual(
            allowed_agent_transitions("disabled"),
            frozenset({"pending", "decommissioned"}),
        )
        self.assertFalse(can_transition_agent("disabled", "active"))
        self.assertTrue(can_transition_agent("disabled", "pending"))

    def test_rejected_requires_administrative_reset_to_pending(self):
        self.assertEqual(
            allowed_agent_transitions("rejected"),
            frozenset({"pending", "decommissioned"}),
        )
        self.assertFalse(can_transition_agent("rejected", "pairing"))
        self.assertTrue(can_transition_agent("rejected", "pending"))

    def test_active_can_be_decommissioned(self):
        result = transition_agent("active", "decommissioned")
        self.assertEqual(result.current, "active")
        self.assertEqual(result.target, "decommissioned")
        self.assertTrue(result.changed)

    def test_offline_can_be_decommissioned(self):
        self.assertTrue(
            can_transition_agent("offline", "decommissioned")
        )

    def test_decommissioned_is_terminal(self):
        self.assertEqual(
            allowed_agent_transitions("decommissioned"),
            frozenset(),
        )
        self.assertFalse(
            can_transition_agent("decommissioned", "active")
        )
        with self.assertRaises(InvalidAgentTransition):
            transition_agent("decommissioned", "active")

    def test_same_state_is_idempotent_noop(self):
        result = transition_agent("offline", "offline")
        self.assertFalse(result.changed)
        self.assertEqual(result.target, "offline")


if __name__ == "__main__":
    unittest.main()
