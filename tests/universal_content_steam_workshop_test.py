#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "core",):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from steam_workshop_resolver import SteamWorkshopError, normalize_published_file_id, resolve_workshop_item


class SteamWorkshopResolverTest(unittest.TestCase):
    def test_normalizes_id_canonical_and_official_url(self):
        self.assertEqual(normalize_published_file_id("123456789"), "123456789")
        self.assertEqual(normalize_published_file_id("221100:123456789", expected_app_id="221100"), "123456789")
        self.assertEqual(
            normalize_published_file_id("https://steamcommunity.com/sharedfiles/filedetails/?id=123456789"),
            "123456789",
        )

    def test_rejects_untrusted_or_mismatched_references(self):
        for value in (
            "http://steamcommunity.com/sharedfiles/filedetails/?id=123",
            "https://example.com/sharedfiles/filedetails/?id=123",
            "https://steamcommunity.com/sharedfiles/filedetails/?id=123&id=456",
            "javascript:alert(1)",
        ):
            with self.subTest(value=value), self.assertRaises(SteamWorkshopError):
                normalize_published_file_id(value)
        with self.assertRaises(SteamWorkshopError):
            normalize_published_file_id("108600:123", expected_app_id="221100")

    def test_resolves_public_metadata_and_builds_agent_package(self):
        calls = []
        def transport(published_file_id):
            calls.append(published_file_id)
            return {"response": {"publishedfiledetails": [{
                "result": 1,
                "publishedfileid": published_file_id,
                "consumer_app_id": 221100,
                "title": "Example DayZ Mod",
                "creator": "76561198000000000",
                "time_updated": 1700000000,
            }]}}
        result = resolve_workshop_item("https://steamcommunity.com/sharedfiles/filedetails/?id=987654321", expected_app_id="221100", transport=transport)
        self.assertEqual(calls, ["987654321"])
        self.assertEqual(result["provider"], "steam-workshop")
        self.assertEqual(result["package_id"], "221100:987654321")
        self.assertEqual(result["metadata"]["title"], "Example DayZ Mod")

    def test_rejects_item_from_another_game(self):
        def transport(published_file_id):
            return {"response": {"publishedfiledetails": [{
                "result": 1,
                "publishedfileid": published_file_id,
                "consumer_app_id": 108600,
            }]}}
        with self.assertRaisesRegex(SteamWorkshopError, "does not belong"):
            resolve_workshop_item("123", expected_app_id="221100", transport=transport)

    def test_rejects_missing_or_spoofed_response_identity(self):
        with self.assertRaises(SteamWorkshopError):
            resolve_workshop_item("123", expected_app_id="221100", transport=lambda _: {"response": {"publishedfiledetails": []}})
        with self.assertRaisesRegex(SteamWorkshopError, "identity mismatch"):
            resolve_workshop_item("123", expected_app_id="221100", transport=lambda _: {"response": {"publishedfiledetails": [{"result": 1, "publishedfileid": "456", "consumer_app_id": 221100}]}})


if __name__ == "__main__":
    unittest.main()
