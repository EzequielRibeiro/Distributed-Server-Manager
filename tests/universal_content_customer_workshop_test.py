#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "core", ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from customer_content_workspace import CustomerContentWorkspaceService


class _Workspace:
    def __init__(self, *, game_id="dayz", runtime_id="dayz.stable", workshop_allowed=True):
        self.root = ROOT
        self.game_id = game_id
        self.runtime_id = runtime_id
        self.repo = SimpleNamespace(workspace_policy=lambda _: {})
        self.policy = SimpleNamespace(
            modifications_allowed=workshop_allowed,
            mods_allowed=False,
            plugins_allowed=False,
            workshop_allowed=workshop_allowed,
            external_upload_allowed=False,
            custom_runtime_allowed=False,
        )

    def require(self, user, instance_id, permission):
        return {
            "id": instance_id,
            "game_id": self.game_id,
            "runtime_id": self.runtime_id,
            "agent_id": "agent-1",
        }

    def _contract_policy(self, context, policy):
        return {}, self.policy


class _Content:
    def __init__(self):
        self.puts = []

    def put(self, payload, requested_by=None):
        self.puts.append((dict(payload), requested_by))
        return {"changed": True, "assignment": dict(payload)}

    def put_many(self, payloads, requested_by=None):
        items = [dict(payload) for payload in payloads]
        for payload in items:
            self.puts.append((dict(payload), requested_by))
        return {"changed": True, "assignments": items}


def _service(*, game_id="dayz", runtime_id="dayz.stable", workshop_allowed=True, resolver=None):
    service = CustomerContentWorkspaceService.__new__(CustomerContentWorkspaceService)
    service.workspace = _Workspace(game_id=game_id, runtime_id=runtime_id, workshop_allowed=workshop_allowed)
    service.content = _Content()
    service.workshop_resolver = resolver or (lambda reference, expected_app_id: {
        "provider": "steam-workshop",
        "package_id": f"{expected_app_id}:987654321",
        "published_file_id": "987654321",
        "consumer_app_id": str(expected_app_id),
        "metadata": {"published_file_id": "987654321", "consumer_app_id": str(expected_app_id), "title": "Safe Mod"},
    })
    return service


class CustomerWorkshopIntegrationTest(unittest.TestCase):
    def test_dayz_uses_catalog_workshop_app_id_and_persists_canonical_package(self):
        seen = []
        def resolver(reference, *, expected_app_id):
            seen.append((reference, expected_app_id))
            return {
                "provider": "steam-workshop",
                "package_id": f"{expected_app_id}:987654321",
                "published_file_id": "987654321",
                "consumer_app_id": expected_app_id,
                "metadata": {"published_file_id": "987654321", "consumer_app_id": expected_app_id, "title": "Safe Mod"},
            }
        service = _service(resolver=resolver)
        service.install({"username": "u"}, "i1", {
            "content_id": "mod-a",
            "content_type": "workshop",
            "provider": "steam-workshop",
            "artifact": {"url": "https://steamcommunity.com/sharedfiles/filedetails/?id=987654321"},
        })
        payload, requested_by = service.content.puts[-1]
        self.assertEqual(seen, [("https://steamcommunity.com/sharedfiles/filedetails/?id=987654321", "221100")])
        self.assertEqual(payload["provider"], "steam-workshop")
        self.assertEqual(payload["artifact"], {"provider": "steam-workshop", "package_id": "221100:987654321", "auth": "required"})
        self.assertEqual(payload["provenance"]["steam_workshop"]["consumer_app_id"], "221100")
        self.assertEqual(payload["metadata"]["steam_workshop"]["title"], "Safe Mod")
        self.assertNotIn("url", payload["artifact"])
        self.assertEqual(requested_by, "u")

    def test_dayz_vpp_installs_cf_dependency_server_owned(self):
        seen = []
        def resolver(reference, *, expected_app_id):
            published = str(reference).split(":")[-1]
            seen.append((published, expected_app_id))
            title = "VPPAdminTools" if published == "1828439124" else "CF"
            return {
                "provider": "steam-workshop",
                "package_id": f"{expected_app_id}:{published}",
                "published_file_id": published,
                "consumer_app_id": expected_app_id,
                "metadata": {
                    "published_file_id": published,
                    "consumer_app_id": expected_app_id,
                    "title": title,
                    "time_updated": 1784106916 if published == "1828439124" else 1784000000,
                },
            }
        service = _service(resolver=resolver)
        result = service.install({"username": "u"}, "i1", {
            "content_id": "steam-workshop:1828439124",
            "content_type": "workshop",
            "provider": "steam-workshop",
            "artifact": {"package_id": "1828439124"},
        })
        self.assertEqual(seen, [("1828439124", "221100"), ("1559212036", "221100")])
        self.assertEqual(result["assignment"]["dependencies"], ["steam-workshop:1559212036"])
        self.assertEqual([item["content_id"] for item in result["dependencies"]], ["steam-workshop:1559212036"])
        cf = result["dependencies"][0]
        self.assertEqual(cf["artifact"]["package_id"], "221100:1559212036")
        self.assertTrue(cf["metadata"]["dependency"]["auto_managed"])
        self.assertEqual(cf["metadata"]["dependency"]["required_by"], "1828439124")

    def test_project_zomboid_uses_its_consumer_app_id(self):
        seen = []
        service = _service(game_id="projectzomboid", runtime_id="projectzomboid.stable", resolver=lambda reference, *, expected_app_id: (
            seen.append(expected_app_id) or {
                "provider": "steam-workshop", "package_id": f"{expected_app_id}:123",
                "published_file_id": "123", "consumer_app_id": expected_app_id,
                "metadata": {"published_file_id": "123", "consumer_app_id": expected_app_id},
            }
        ))
        service.install({"username": "u"}, "i1", {"content_id": "mod-b", "content_type": "workshop", "provider": "steam", "artifact": {"package_id": "123"}})
        self.assertEqual(seen, ["108600"])
        payload = service.content.puts[-1][0]
        self.assertEqual(payload["artifact"]["package_id"], "108600:123")
        self.assertEqual(payload["artifact"]["auth"], "anonymous")
        self.assertEqual(payload["activation_state"], "disabled")
        self.assertEqual(
            payload["metadata"]["activation"],
            {"adapter": "project-zomboid", "mode": "mod"},
        )

    def test_customer_cannot_downgrade_runtime_owned_workshop_auth(self):
        service = _service()
        service.install({"username": "u"}, "i1", {
            "content_id": "mod-auth",
            "content_type": "workshop",
            "provider": "steam-workshop",
            "artifact": {
                "package_id": "987654321",
                "auth": "anonymous",
            },
        })
        payload = service.content.puts[-1][0]
        self.assertEqual(payload["artifact"]["auth"], "required")

    def test_runtime_without_workshop_identity_fails_closed(self):
        service = _service(game_id="minecraft", runtime_id="minecraft.vanilla.stable")
        with self.assertRaises(PermissionError):
            service.install({"username": "u"}, "i1", {"content_id": "x", "content_type": "workshop", "provider": "steam-workshop", "artifact": {"package_id": "123"}})


if __name__ == "__main__":
    unittest.main()
