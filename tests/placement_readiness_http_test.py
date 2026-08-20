#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dashboard"))

import placement_readiness_http as api


class _Dialect:
    placeholder = "?"


class _Session:
    def __init__(self, row):
        self.row = row

    def execute(self, sql, params):
        return self

    def fetchone(self):
        return self.row


class _Repository:
    def __init__(self, backend, row, candidates):
        self.backend = backend
        self.dialect = _Dialect()
        self._row = row
        self._candidates = candidates

    def initialize(self):
        return None

    @contextmanager
    def session(self):
        yield _Session(self._row)

    def candidates(self, controller_id):
        self.controller_id = controller_id
        return list(self._candidates)


class PlacementReadinessHttpTest(unittest.TestCase):
    def _patch_repository(self, row, candidates):
        instance = _Repository(object(), row, candidates)
        return instance, mock.patch.object(api, "LocationRepository", return_value=instance)

    def test_customer_with_candidate_is_ready(self):
        repository, patcher = self._patch_repository(
            {"controller_id": "controller-a", "status": "active"},
            [{"agent_id": "agent-a"}],
        )
        user = {"role": "customer", "scope_id": "customer-a"}
        with patcher:
            result = api.placement_readiness_for_customer(user, object())
        self.assertEqual(repository.controller_id, "controller-a")
        self.assertEqual(result, {"placement_ready": True, "state": "available"})

    def test_customer_without_candidate_is_not_ready(self):
        _, patcher = self._patch_repository(
            {"controller_id": "controller-a", "status": "active"},
            [],
        )
        user = {"role": "customer", "scope_id": "customer-a"}
        with patcher:
            result = api.placement_readiness_for_customer(user, object())
        self.assertEqual(result, {"placement_ready": False, "state": "unavailable"})
        self.assertNotIn("reason", result)
        self.assertNotIn("eligible_agents", result)

    def test_non_customer_is_rejected(self):
        with self.assertRaises(PermissionError):
            api.placement_readiness_for_customer({"role": "admin"}, object())

    def test_dispatch_returns_customer_safe_403(self):
        result = api.dispatch_placement_readiness_get(
            api.PLACEMENT_READINESS_PATH,
            user=None,
            backend=object(),
        )
        self.assertEqual(result[0], 403)
        self.assertEqual(result[1]["error"], "forbidden")


if __name__ == "__main__":
    unittest.main()
