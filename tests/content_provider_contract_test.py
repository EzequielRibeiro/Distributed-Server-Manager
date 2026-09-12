#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.content_provider_contract import (
    ContentProviderContractError,
    OFFICIAL_CONTENT_PROVIDERS,
    provider_request,
    requires_agent_capability,
)


class ContentProviderContractTest(unittest.TestCase):
    def test_workshop_is_first_class_official_provider(self):
        request = provider_request({
            "content_id": "cf",
            "game_id": "dayz",
            "content_type": "workshop",
            "version": "latest",
            "provider": "steam-workshop",
            "artifact": {"package_id": "221100:1559212036"},
        })
        self.assertEqual(request["provider"], "steam-workshop")
        self.assertEqual(request["package_id"], "221100:1559212036")
        self.assertTrue(requires_agent_capability(request))
        self.assertIn("steam-workshop", OFFICIAL_CONTENT_PROVIDERS)

    def test_remote_url_becomes_package_without_becoming_command(self):
        request = provider_request({
            "content_id": "map-one",
            "game_id": "example",
            "content_type": "map",
            "provider": "http-archive",
            "artifact": {"url": "https://example.invalid/map.zip"},
        })
        self.assertEqual(request["package_id"], "https://example.invalid/map.zip")
        self.assertTrue(requires_agent_capability(request))

    def test_agent_local_resolved_path_skips_provider_acquisition(self):
        request = provider_request({
            "content_id": "mod-one",
            "game_id": "example",
            "content_type": "mod",
            "provider": "steam-workshop",
            "artifact": {
                "package_id": "123:456",
                "resolved_path": "providers/steam-workshop/123/456",
            },
        })
        self.assertFalse(requires_agent_capability(request))
        self.assertEqual(request["resolved_path"], "providers/steam-workshop/123/456")

    def test_controller_cannot_inject_executable_provider_payload(self):
        for key in ("command", "shell", "exec", "script"):
            with self.subTest(key=key):
                with self.assertRaises(ContentProviderContractError):
                    provider_request({
                        "content_id": "bad",
                        "provider": "custom",
                        "artifact": {"package_id": "x", key: "rm -rf /"},
                    })

    def test_invalid_provider_name_and_missing_package_fail_closed(self):
        with self.assertRaises(ContentProviderContractError):
            provider_request({"content_id": "bad", "provider": "../steam"})
        with self.assertRaises(ContentProviderContractError):
            provider_request({"content_id": "bad", "provider": "steam-workshop"})


if __name__ == "__main__":
    unittest.main()
