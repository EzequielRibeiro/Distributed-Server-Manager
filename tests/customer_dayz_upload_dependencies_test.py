#!/usr/bin/env python3
"""Isolated regression: existing Workshop items remain attached to uploaded DayZ maps."""
from __future__ import annotations
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dashboard"))
from customer_content_upload_service import CustomerContentUploadService


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


if __name__ == "__main__":
    unittest.main()
