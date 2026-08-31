#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "dashboard", ROOT / "database"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from alert_management_http import (
    IDENTITY_COLLISION_RULE_ID,
    generic_alert_action_allowed,
)


class IdentityCollisionResolutionGuardTest(unittest.TestCase):
    def test_generic_resolve_is_blocked_for_identity_collision(self) -> None:
        alert = {"rule_id": IDENTITY_COLLISION_RULE_ID}
        self.assertFalse(generic_alert_action_allowed(alert, "resolve"))

    def test_non_destructive_actions_remain_available(self) -> None:
        alert = {"rule_id": IDENTITY_COLLISION_RULE_ID}
        for action in ("acknowledge", "note", "suppress", "reopen"):
            with self.subTest(action=action):
                self.assertTrue(generic_alert_action_allowed(alert, action))

    def test_generic_alerts_still_allow_resolve(self) -> None:
        self.assertTrue(
            generic_alert_action_allowed({"rule_id": "agent.offline"}, "resolve")
        )

    def test_frontends_hide_generic_resolve_for_identity_collision(self) -> None:
        home = (ROOT / "dashboard" / "web" / "dashboard-home-v3.js").read_text(
            encoding="utf-8"
        )
        observability = (ROOT / "dashboard" / "web" / "observability.js").read_text(
            encoding="utf-8"
        )
        self.assertIn('ruleId !== "agent.identity_collision"', home)
        self.assertIn('ruleId!=="agent.identity_collision"', observability)


if __name__ == "__main__":
    unittest.main()
