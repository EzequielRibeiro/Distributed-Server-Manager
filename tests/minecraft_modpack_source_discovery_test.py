#!/usr/bin/env python3
"""Upstream serverpack discovery never bypasses provider downloads or weak hashes."""
import sys
import unittest
from pathlib import Path
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "dashboard"))

from customer_modpack_source_discovery import discover_modpack, _cdn_url
from minecraft_content_resolver import MinecraftContentResolverError

MAIN = {"id": 123, "modId": 99, "isAvailable": True,
        "isServerPack": False, "serverPackFileId": 456,
        "gameVersions": ["26.1.2", "NeoForge"],
        "fileDate": "2026-09-25T12:00:00Z"}
PACK = {"id": 456, "modId": 99, "isAvailable": True,
        "isServerPack": True, "fileName": "ServerFiles.zip",
        "fileLength": 500_000_000,
        "hashes": [{"algo": 1, "value": "a" * 40}],
        "downloadUrl": "https://mediafilez.forgecdn.net/files/456/ServerFiles.zip",
        "gameVersions": []}


def cf_fixture(*, project_override=None, main_override=None, pack_override=None, reject_download=False):
    calls = []
    project = {"id": 99, "gameId": 432, "classId": 4471,
               "name": "Test Modpack", "allowModDistribution": True}
    project.update(project_override or {})
    main = {**MAIN, **(main_override or {})}
    pack = {**PACK, **(pack_override or {})}

    def request(url, headers):
        calls.append(url)
        assert headers == {"x-api-key": "test-key"}
        if "/categories?" in url:
            return {"data": [{"id": 4471, "name": "Modpacks", "slug": "modpacks", "isClass": True}]}
        if url.endswith("/mods/99"):
            return {"data": project}
        if "/mods/99/files?" in url:
            return {"data": [main]}
        if url.endswith("/mods/99/files/123"):
            return {"data": main}
        if url.endswith("/mods/99/files/456"):
            return {"data": pack}
        if url.endswith("/mods/99/files/456/download-url"):
            if reject_download:
                raise MinecraftContentResolverError("Invalid API key") from HTTPError(
                    url, 403, "Forbidden", None, None)
            return {"data": "https://edge.forgecdn.net/files/456/ServerFiles.zip"}
        raise AssertionError(f"Unexpected provider endpoint: {url}")

    return request, calls


class ModpackDiscoveryTest(unittest.TestCase):
    def discover_cf(self, requester, version_ref=""):
        return discover_modpack("curseforge", "99", "26.1.2", "neoforge",
                                version_ref, requester=requester,
                                load_secret=lambda ignored: "test-key")

    def test_curseforge_follows_official_serverpack_file_id_without_mod_downloads(self):
        requester, calls = cf_fixture()
        result = self.discover_cf(requester)
        self.assertEqual(result["mode"], "serverpack_auto")
        self.assertEqual(result["serverpack_file_id"], "456")
        self.assertEqual(result["sha1"], "a" * 40)
        self.assertIn("forgecdn.net", result["download_url"])
        self.assertFalse(any("/download-url" in url for url in calls))
        self.assertFalse(any("v1/mods/1/files/" in url for url in calls))

    def test_explicit_main_version_and_serverpack_version(self):
        requester, _ = cf_fixture()
        self.assertEqual(self.discover_cf(requester, "123")["serverpack_file_id"], "456")
        # Some publishers expose the serverpack as a standalone file with
        # explicit Minecraft/loader tags.
        standalone = {**PACK, "gameVersions": ["26.1.2", "NeoForge"]}
        def direct(url, headers):
            if url.endswith("/files/456"):
                return {"data": standalone}
            return requester(url, headers)
        self.assertEqual(self.discover_cf(direct, "456")["mode"], "serverpack_auto")

    def test_author_restriction_blocks_even_an_existing_cdn_url(self):
        requester, _ = cf_fixture(project_override={"allowModDistribution": False})
        result = self.discover_cf(requester)
        self.assertEqual(result["mode"], "manual_required")
        self.assertNotIn("download_url", result)
        self.assertIn("autor", result["reason"])

    def test_file_level_403_is_manual_fallback_not_global_api_error(self):
        requester, calls = cf_fixture(pack_override={"downloadUrl": None}, reject_download=True)
        result = self.discover_cf(requester)
        self.assertEqual(result["mode"], "manual_required")
        self.assertIn("403", result["reason"])
        self.assertIn("/files/456/download-url", calls[-1])
        self.assertNotIn("download_url", result)

    def test_unknown_cdn_hash_or_mismatched_version_never_auto_downloads(self):
        for overrides in (
            {"downloadUrl": "https://evil.example/ServerFiles.zip"},
            {"downloadUrl": "http://mediafilez.forgecdn.net/files/server.zip"},
            {"hashes": []},
            {"fileLength": 5 * 1024 * 1024 * 1024},
        ):
            with self.subTest(overrides=overrides):
                requester, _ = cf_fixture(pack_override=overrides)
                result = self.discover_cf(requester)
                self.assertNotEqual(result["mode"], "serverpack_auto")
        for override in (
            {"gameVersions": ["26.2", "NeoForge"]},
            {"gameVersions": ["26.1.2", "Forge"]},
            {"isAvailable": False},
        ):
            with self.subTest(override=override):
                requester, _ = cf_fixture(main_override=override)
                result = self.discover_cf(requester)
                self.assertEqual(result["mode"], "no_official_serverpack")

    def test_inconsistent_link_to_nonserverpack_is_rejected(self):
        requester, _ = cf_fixture(pack_override={"isServerPack": False})
        self.assertEqual(self.discover_cf(requester)["mode"], "no_official_serverpack")

    def test_modrinth_uses_verified_mrpack_version_not_generic_zip(self):
        calls = []
        def requester(url, headers):
            calls.append(url)
            if "/project/atmpack/version?" in url:
                return [{"id": "version-1", "project_id": "ABCD1234",
                         "date_published": "2026-09-25T10:00:00Z",
                         "game_versions": ["26.1.2"], "loaders": ["neoforge"],
                         "status": "listed", "version_number": "0.9.0",
                         "files": [{"filename": "client.zip", "primary": True,
                                    "url": "https://cdn.modrinth.com/bad.zip",
                                    "hashes": {"sha512": "b" * 128, "sha1": "a" * 40}},
                                   {"filename": "official.mrpack", "primary": False,
                                    "url": "https://cdn.modrinth.com/data/pack/official.mrpack",
                                    "hashes": {"sha512": "b" * 128, "sha1": "a" * 40}}]}]
            if url.endswith("/project/atmpack"):
                return {"id": "ABCD1234", "project_type": "modpack", "status": "approved"}
            raise AssertionError(url)
        result = discover_modpack("modrinth", "atmpack", "26.1.2", "neoforge", requester=requester)
        self.assertEqual(result["mode"], "managed_modrinth")
        self.assertEqual(result["version_id"], "version-1")
        self.assertTrue(any("loaders=" in url and "game_versions=" in url for url in calls))

    def test_modrinth_file_cannot_impersonate_official_cdn(self):
        def requester(url, headers):
            if "/version?" in url:
                return [{"id": "v1", "game_versions": ["26.1.2"], "loaders": ["neoforge"],
                         "files": [{"filename": "pack.mrpack", "url": "https://bad.invalid/pack.mrpack",
                                    "hashes": {"sha512": "b" * 128, "sha1": "a" * 40}}]}]
            return {"id": "ABCD1234", "project_type": "modpack", "status": "approved"}
        self.assertEqual(
            discover_modpack("modrinth", "atmpack", "26.1.2", "neoforge", requester=requester)["mode"],
            "no_compatible_mrpack"
        )

    def test_url_allowlist_is_https_and_exact_host_constrained(self):
        self.assertIsNone(_cdn_url("https://evilforgecdn.net/a.zip", "curseforge"))
        self.assertIsNone(_cdn_url("https://cdn.modrinth.com.evil.invalid/a.mrpack", "modrinth"))
        self.assertIsNone(_cdn_url("https://u:p@mediafilez.forgecdn.net/x.zip", "curseforge"))
        self.assertIsNone(_cdn_url("http://mediafilez.forgecdn.net/x.zip", "curseforge"))
        self.assertTrue(_cdn_url("https://edge.forgecdn.net/x.zip", "curseforge"))

if __name__ == "__main__":
    unittest.main()
