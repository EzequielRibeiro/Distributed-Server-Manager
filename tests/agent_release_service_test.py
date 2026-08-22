#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent_release_service import (
    AgentReleaseError,
    list_agent_releases,
    release_supports_platform,
    resolve_agent_release,
)


def release(tag: str, *, prerelease: bool = False, draft: bool = False, platforms=("linux",)):
    version = tag.lstrip("v")
    assets = []
    if "linux" in platforms:
        name = f"capivara-agent-linux-{version}.tar.gz"
        assets.extend([{"name": name}, {"name": name + ".sha256"}])
    if "windows" in platforms:
        name = f"capivara-agent-windows-{version}.zip"
        assets.extend([{"name": name}, {"name": name + ".sha256"}])
    return {
        "tag_name": tag,
        "name": tag,
        "draft": draft,
        "prerelease": prerelease,
        "published_at": "2026-08-22T00:00:00Z",
        "html_url": f"https://github.example/releases/{tag}",
        "assets": assets,
    }


class AgentReleaseServiceTest(unittest.TestCase):
    def test_platform_requires_archive_and_checksum(self):
        item = release("v2.1.0", platforms=("linux", "windows"))
        self.assertTrue(release_supports_platform(item, "linux"))
        self.assertTrue(release_supports_platform(item, "windows"))
        item["assets"] = [{"name": "capivara-agent-linux-2.1.0.tar.gz"}]
        self.assertFalse(release_supports_platform(item, "linux"))

    @patch("agent_release_service._request_json")
    def test_list_filters_drafts_prereleases_and_incompatible_assets(self, request_json):
        request_json.return_value = [
            release("v2.3.0"),
            release("v2.4.0-beta.1", prerelease=True),
            release("v2.2.0", draft=True),
            release("v2.1.0", platforms=("windows",)),
        ]
        result = list_agent_releases("linux")
        self.assertEqual([item["tag"] for item in result], ["v2.3.0"])

    @patch("agent_release_service._request_json")
    def test_prereleases_can_be_requested_explicitly(self, request_json):
        request_json.return_value = [
            release("v2.4.0-beta.1", prerelease=True),
            release("v2.3.0"),
        ]
        result = list_agent_releases("linux", include_prereleases=True)
        self.assertEqual([item["tag"] for item in result], ["v2.4.0-beta.1", "v2.3.0"])

    @patch("agent_release_service._request_json")
    def test_explicit_release_is_validated_before_install(self, request_json):
        request_json.return_value = release("v2.3.0")
        result = resolve_agent_release("v2.3.0", "linux")
        self.assertEqual(result["tag"], "v2.3.0")
        request_json.assert_called_once_with("releases/tags/v2.3.0")

    @patch("agent_release_service._request_json")
    def test_release_without_required_assets_is_rejected(self, request_json):
        request_json.return_value = release("v2.3.0", platforms=("windows",))
        with self.assertRaisesRegex(AgentReleaseError, "required linux package and checksum"):
            resolve_agent_release("v2.3.0", "linux")


if __name__ == "__main__":
    unittest.main()
