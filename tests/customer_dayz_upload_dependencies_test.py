#!/usr/bin/env python3
"""Isolated regression: existing Workshop items remain attached to uploaded DayZ maps."""
from __future__ import annotations
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dashboard"))
sys.path.insert(0, str(ROOT / "database"))
from customer_content_upload_service import CustomerContentUploadService
from customer_content_workspace import CustomerContentWorkspaceService


class DayZUploadedMapDependenciesTest(unittest.TestCase):
    def _service(self):
        service = object.__new__(CustomerContentUploadService)
        service._transfer = lambda user, transfer_id: {
            "transfer_id": transfer_id, "status": "completed",
        }
        calls = []
        def finalize(user, transfer_id, payload, extra_assignments=None):
            calls.append((payload, extra_assignments))
            return {"assignment": payload, "new": extra_assignments}
        service._finalize = finalize
        return service, calls

    def test_new_and_preexisting_workshop_dependencies_both_linked(self):
        service, calls = self._service()
        new = [{"content_id": "steam-workshop:4444"}]
        result = service.finalize_dayz_community_map(
            {"username": "customer"}, "transfer-test", {"content_id": "dayz-map:custom"},
            new,
            dependency_content_ids=["steam-workshop:1234", "steam-workshop:4444"],
        )
        self.assertEqual(
            result["assignment"]["dependencies"],
            ["steam-workshop:1234", "steam-workshop:4444"],
        )
        self.assertEqual(result["assignment"]["activation_state"], "disabled")
        self.assertEqual(result["assignment"]["content_type"], "map")
        self.assertEqual(calls[0][1], new)

    def test_only_already_installed_dependencies_remain_linked(self):
        service, calls = self._service()
        result = service.finalize_dayz_community_map(
            {"username": "customer"}, "transfer-test", {"content_id": "dayz-map:another"},
            [], dependency_content_ids=["steam-workshop:1234"],
        )
        self.assertEqual(result["assignment"]["dependencies"], ["steam-workshop:1234"])
        self.assertEqual(calls[0][1], [])

    def test_fallback_for_previous_internal_callers(self):
        service, _ = self._service()
        result = service.finalize_dayz_community_map(
            {"username": "customer"}, "transfer-test", {"content_id": "dayz-map:test"},
            [{"content_id": "steam-workshop:9"}],
        )
        self.assertEqual(result["assignment"]["dependencies"], ["steam-workshop:9"])

    def test_http_passes_authoritative_resolved_dependency_ids(self):
        source = (ROOT / "dashboard/customer_dayz_http.py").read_text(encoding="utf-8")
        self.assertIn('dependency_content_ids=prepared["dependencies"]', source)


class DayZWorkshopPolicyReuseTest(unittest.TestCase):
    def _service(self, *, workshop_allowed):
        service = object.__new__(CustomerContentWorkspaceService)
        service._context_policy = lambda _user, _instance_id, _permission: (
            {"game_id": "dayz"}, SimpleNamespace(workshop_allowed=workshop_allowed),
        )
        service.content = SimpleNamespace(get=lambda _instance_id, _content_id: {
            "content_id": "steam-workshop:1234", "desired_state": "installed",
        })
        return service

    def test_existing_workshop_item_denied_by_effective_contract(self):
        service = self._service(workshop_allowed=False)
        with self.assertRaisesRegex(PermissionError, "workshop content is not allowed"):
            service.dayz_community_workshop_dependencies({}, "test-dayz", ["1234"])

    def test_existing_workshop_item_retained_when_authorized(self):
        service = self._service(workshop_allowed=True)
        result = service.dayz_community_workshop_dependencies({}, "test-dayz", ["1234"])
        self.assertEqual(result["dependencies"], ["steam-workshop:1234"])
        self.assertEqual(result["items"], [])
        self.assertEqual(result["existing_items"][0]["content_id"], "steam-workshop:1234")

    def test_map_without_workshop_items_does_not_require_workshop_permission(self):
        service = self._service(workshop_allowed=False)
        result = service.dayz_community_workshop_dependencies({}, "test-dayz", [])
        self.assertEqual(result["dependencies"], [])
        self.assertEqual(result["items"], [])



if __name__ == "__main__":
    unittest.main()
