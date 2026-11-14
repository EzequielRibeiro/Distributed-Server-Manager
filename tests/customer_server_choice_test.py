#!/usr/bin/env python3
"""Customer host selection must not leak internal IDs or bypass placement."""
from __future__ import annotations

import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "dashboard", ROOT / "database"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from customer_server_choice import public_server_ref, resolve_server_ref
from instance_placement import resolve_instance_placement


class _Session:
    def execute(self, _sql, _params):
        return self

    def fetchone(self):
        return {"id": 42, "customer_code": "CLI-000042",
                "controller_id": "controller-a", "status": "active"}


class _Repository:
    backend = object()
    dialect = type("Dialect", (), {"placeholder": "?"})()

    @contextmanager
    def session(self):
        yield _Session()


CANDIDATES = [
    {"agent_id": "secret-agent-sp", "region_id": "br-sudeste"},
    {"agent_id": "secret-agent-us", "region_id": "us-east"},
]


class CustomerServerChoiceTest(unittest.TestCase):
    def test_public_server_ref_is_stable_and_does_not_expose_agent_id(self):
        ref = public_server_ref("controller-a", "secret-agent-sp")
        self.assertTrue(ref.startswith("srv-"))
        self.assertEqual(len(ref), 28)
        self.assertNotIn("secret-agent-sp", ref)
        self.assertEqual(ref, public_server_ref("controller-a", "secret-agent-sp"))
        self.assertNotEqual(ref, public_server_ref("controller-b", "secret-agent-sp"))

    def test_scoped_resolution_accepts_only_own_region_candidate(self):
        ref = public_server_ref("controller-a", "secret-agent-sp")
        self.assertEqual(resolve_server_ref("controller-a", ref, CANDIDATES,
                                            region_id="br-sudeste"), "secret-agent-sp")
        with self.assertRaises(ValueError):
            resolve_server_ref("controller-a", ref, CANDIDATES, region_id="us-east")
        with self.assertRaises(ValueError):
            resolve_server_ref("controller-b", ref, CANDIDATES, region_id="br-sudeste")
        with self.assertRaises(ValueError):
            resolve_server_ref("controller-a", "srv-" + "f" * 24, CANDIDATES)
        with self.assertRaises(ValueError):
            resolve_server_ref("controller-a", "../../etc/passwd", CANDIDATES)

    def test_explicit_choice_reuses_normal_placement_eligibility(self):
        ref = public_server_ref("controller-a", "secret-agent-sp")
        decision = {
            "agent_id": "secret-agent-sp", "node_id": "secret-node",
            "region_id": "br-sudeste", "datacenter_id": "secret-dc",
            "score": -1.0, "reason": "explicit-scoped",
            "requirements": {},
        }
        with patch("instance_placement._customer_id", return_value=42), \
             patch("instance_placement.region_preference_for_creation", return_value={
                 "region_id": "br-sudeste", "allow_cross_region": False,
             }), \
             patch("instance_placement.LocationRepository") as locations, \
             patch("instance_placement.choose_agent_for_instance", return_value=decision) as choose, \
             patch("instance_placement.UniversalEventRepository"):
            locations.return_value.candidates.return_value = CANDIDATES
            result = resolve_instance_placement(
                {"role": "customer", "scope_id": "CLI-000042"},
                {"game": "dayz", "runtime_id": "dayz.stable",
                 "placement": {"region_id": "br-sudeste", "server_ref": ref}},
                _Repository(),
            )
        self.assertEqual(result["agent_id"], "secret-agent-sp")
        self.assertEqual(choose.call_args.kwargs["required_agent_id"], "secret-agent-sp")
        self.assertEqual(choose.call_args.kwargs["preferred_region_id"], "br-sudeste")

    def test_foreign_or_stale_choice_is_rejected_before_placement(self):
        ref = public_server_ref("controller-b", "secret-agent-sp")
        with patch("instance_placement._customer_id", return_value=42), \
             patch("instance_placement.region_preference_for_creation", return_value={
                 "region_id": "br-sudeste", "allow_cross_region": False,
             }), \
             patch("instance_placement.LocationRepository") as locations, \
             patch("instance_placement.choose_agent_for_instance") as choose:
            locations.return_value.candidates.return_value = CANDIDATES
            with self.assertRaisesRegex(ValueError, "Servidor selecionado indisponível"):
                resolve_instance_placement(
                    {"role": "customer", "scope_id": "CLI-000042"},
                    {"game": "dayz", "placement": {
                        "region_id": "br-sudeste", "server_ref": ref,
                    }},
                    _Repository(),
                )
            choose.assert_not_called()


if __name__ == "__main__":
    unittest.main()
