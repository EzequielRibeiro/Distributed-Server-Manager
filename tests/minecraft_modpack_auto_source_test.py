#!/usr/bin/env python3
"""Provider discovery, authorized ZIP staging and customer UI safety tests."""
from __future__ import annotations

import hashlib
import io
import socket
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for folder in ("core", "dashboard", "database"):
    entry = str(ROOT / folder)
    if entry not in sys.path:
        sys.path.insert(0, entry)

from customer_content_upload_service import CustomerContentUploadService, _safe_external_url
from tests.universal_content_external_upload_test import service

USER = {"username": "alice"}
DISCOVERED = {
    "provider": "curseforge", "mode": "serverpack_auto",
    "project_id": "99", "serverpack_file_id": "456",
    "file_name": "ServerFiles.zip", "size_bytes": 9,
    "sha1": hashlib.sha1(b"123456789").hexdigest(),
    "official_page": "https://www.curseforge.com/minecraft/modpacks/99/files/456",
    "download_url": "https://edge.forgecdn.net/files/456/ServerFiles.zip",
}


class HTTPResponse(io.BytesIO):
    def __init__(self, data=b"123456789"):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def geturl(self):
        return DISCOVERED["download_url"]


class Opener:
    def __init__(self, data):
        self.data = data

    def open(self, request, timeout):
        assert timeout == 30
        assert request.full_url == DISCOVERED["download_url"]
        return HTTPResponse(self.data)


class ProviderAutoSourceTest(unittest.TestCase):
    def test_api_discovery_enforces_owner_contract_and_runtime(self):
        s = service()
        with patch("customer_content_upload_service.runtime_definition", return_value={"loader": "neoforge"}), patch(
                "customer_content_upload_service.detect_modpack_source",
                return_value=dict(DISCOVERED)) as discover:
            result = s.discover_provider_modpack(
                USER, "i1", {"provider": "curseforge", "project_id": "99"})
        self.assertEqual(result["serverpack_file_id"], "456")
        discover.assert_called_once_with("curseforge", "99", "1.21.1", "neoforge", "")
        self.assertEqual(s.workspace.calls[-1], ("i1", "content.install"))

    def test_auto_download_stages_only_verified_provider_bytes(self):
        s = service()
        with patch.object(s, "discover_provider_modpack", return_value=dict(DISCOVERED)), patch(
                "customer_content_upload_service.socket.getaddrinfo",
                return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]), patch(
                "customer_content_upload_service.build_opener", return_value=Opener(b"123456789")):
            result = s.download_discovered_serverpack(USER, "i1", {
                "provider": "curseforge", "project_id": "99", "serverpack_file_id": "456"})
        self.assertEqual(result["source"]["serverpack_file_id"], "456")
        self.assertEqual(s.transfers.created[0]["filename"], "ServerFiles.zip")
        self.assertEqual(s.transfers.staged[-1][2], b"123456789")
        self.assertEqual(s.transfers.item["status"], "queued")

    def test_invalid_source_sha_never_queues_agent_transfer(self):
        s = service()
        with patch.object(s, "discover_provider_modpack", return_value=dict(DISCOVERED)), patch(
                "customer_content_upload_service.socket.getaddrinfo",
                return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]), patch(
                "customer_content_upload_service.build_opener", return_value=Opener(b"12345678X")):
            with self.assertRaisesRegex(ValueError, "SHA-1"):
                s.download_discovered_serverpack(USER, "i1", {
                    "provider": "curseforge", "project_id": "99", "serverpack_file_id": "456"})
        self.assertEqual(s.transfers.staged, [])
        self.assertEqual(s.transfers.item["status"], "cancelled")

    def test_truncated_provider_stream_never_queues_agent_transfer(self):
        s = service()
        truncated = b"12345678"
        class TruncatedResponse(HTTPResponse):
            def __init__(self):
                super().__init__(truncated)
                self.headers["Content-Length"] = "9"
        with patch.object(s, "discover_provider_modpack", return_value=dict(DISCOVERED)), patch(
                "customer_content_upload_service.socket.getaddrinfo",
                return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]), patch(
                "customer_content_upload_service.build_opener",
                return_value=SimpleNamespace(open=lambda request, timeout: TruncatedResponse())):
            with self.assertRaisesRegex(ValueError, "Content-Length"):
                s.download_discovered_serverpack(USER, "i1", {
                    "provider": "curseforge", "project_id": "99", "serverpack_file_id": "456"})
        self.assertEqual(s.transfers.staged, [])
        self.assertEqual(s.transfers.item["status"], "cancelled")

    def test_manual_required_cannot_be_bypassed_by_user_submitted_file_id(self):
        s = service()
        with patch.object(s, "discover_provider_modpack",
                          return_value={"mode": "manual_required", "reason": "HTTP 403"}):
            with self.assertRaisesRegex(ValueError, "403"):
                s.download_discovered_serverpack(USER, "i1", {
                    "provider": "curseforge", "project_id": "99", "serverpack_file_id": "456"})
        self.assertEqual(s.transfers.created, [])

    def test_changed_or_spoofed_file_id_requires_fresh_discovery(self):
        s = service()
        with patch.object(s, "discover_provider_modpack", return_value=dict(DISCOVERED)):
            with self.assertRaisesRegex(ValueError, "mudou"):
                s.download_discovered_serverpack(USER, "i1", {
                    "provider": "curseforge", "project_id": "99", "serverpack_file_id": "457"})
        self.assertEqual(s.transfers.created, [])

    def test_cdn_host_restriction_applies_to_download_and_redirects(self):
        with patch("customer_content_upload_service.socket.getaddrinfo",
                   return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]):
            self.assertEqual(_safe_external_url(DISCOVERED["download_url"], "forgecdn.net"),
                             DISCOVERED["download_url"])
            with self.assertRaisesRegex(ValueError, "CDN"):
                _safe_external_url("https://example.invalid/ServerFiles.zip", "forgecdn.net")

    def test_ui_calls_discovery_before_install_and_preserves_preview(self):
        js = (ROOT / "dashboard/web/customer-instance-v2.js").read_text()
        http = (ROOT / "dashboard/customer_content_http.py").read_text()
        for marker in ("content/modpack/discover", "serverpack_file_id",
                       "content/modpack/serverpack/download",
                       "source.mode===\"manual_required\"",
                       "source.mode===\"serverpack_auto\"",
                       "source.mode!==\"managed_modrinth\"",
                       "await previewOfficialServerpack",
                       "content/upload/finalize"):
            self.assertIn(marker, js)
        self.assertIn('MODPACK_DISCOVER=PATH+"/modpack/discover"', http)
        self.assertIn('MODPACK_SERVERPACK_DOWNLOAD=PATH+"/modpack/serverpack/download"', http)

if __name__ == "__main__":
    unittest.main()
