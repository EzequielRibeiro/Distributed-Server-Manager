#!/usr/bin/env python3
"""Physical JAR attestation must not accept a matching count with wrong bytes."""
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
from minecraft_serverpack_physical_manifest import (
    MinecraftServerPackPhysicalManifestError,
    attest_serverpack_mods,
)


class PhysicalManifestGateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runtime = Path(self.temp.name) / "runtime"
        (self.runtime / "mods").mkdir(parents=True)
        self.jar = self.runtime / "mods" / "original.jar"
        self.jar.write_bytes(b"mod-original")
        artifact = {"provider": "local", "serverpack_child_v1": True,
                    "ephemeral_upload": True, "bundle_parent_content_id": "pack",
                    "bundle_member": "mods/original.jar", "serverpack_loader": "neoforge",
                    "serverpack_loader_version": "26.1.2.109",
                    "sha256": hashlib.sha256(b"mod-original").hexdigest(),
                    "size_bytes": len(b"mod-original")}
        self.bundle = {"provider": "local", "provider_project_id": "cf-1148445",
                       "provider_version_id": "v14", "minecraft_version": "26.1.2",
                       "loader_id": "neoforge", "loader_version": "26.1.2.109",
                       "manifest_kind": "serverpack-local-v1", "override_roots": [],
                       "members": [{"content_id": "original", "path": "mods/original.jar",
                                    "artifact": artifact, "required": True}]}

    def verify(self):
        return attest_serverpack_mods(self.runtime, instance_id="inst",
                                      content_id="pack", bundle=self.bundle)

    def test_exact_sha256_size_and_name_pass(self):
        self.assertEqual(self.verify()["mod_count"], 1)
        self.assertEqual(len(self.verify()["manifest_sha256"]), 64)

    def test_same_count_wrong_bytes_fails(self):
        self.jar.write_bytes(b"mod-modified")
        with self.assertRaisesRegex(MinecraftServerPackPhysicalManifestError, "SHA-256"):
            self.verify()

    def test_same_count_wrong_size_fails(self):
        self.jar.write_bytes(b"bad")
        with self.assertRaisesRegex(MinecraftServerPackPhysicalManifestError, "size"):
            self.verify()

    def test_same_count_wrong_filename_fails(self):
        self.jar.rename(self.runtime / "mods" / "other.jar")
        with self.assertRaisesRegex(MinecraftServerPackPhysicalManifestError, "unexpected"):
            self.verify()

    def test_unexpected_extra_jar_fails(self):
        (self.runtime / "mods" / "extra.jar").write_bytes(b"extra")
        with self.assertRaisesRegex(MinecraftServerPackPhysicalManifestError, "unexpected"):
            self.verify()

    def test_missing_member_fails(self):
        self.jar.unlink()
        with self.assertRaisesRegex(MinecraftServerPackPhysicalManifestError, "missing"):
            self.verify()

    def test_symlink_jar_fails(self):
        self.jar.unlink()
        self.jar.symlink_to(self.runtime / "other.jar")
        with self.assertRaisesRegex(MinecraftServerPackPhysicalManifestError, "unsafe"):
            self.verify()

    def test_symlink_mods_directory_fails(self):
        self.jar.unlink()
        (self.runtime / "mods").rmdir()
        (self.runtime / "other").mkdir()
        (self.runtime / "mods").symlink_to(self.runtime / "other", target_is_directory=True)
        with self.assertRaisesRegex(MinecraftServerPackPhysicalManifestError, "unsafe"):
            self.verify()

    def test_non_jar_file_fails(self):
        (self.runtime / "mods" / "unexpected.txt").write_text("bad")
        with self.assertRaisesRegex(MinecraftServerPackPhysicalManifestError, "non-JAR"):
            self.verify()

    def test_invalid_manifest_fails_closed(self):
        self.bundle["members"][0]["artifact"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(MinecraftServerPackPhysicalManifestError, "SHA-256"):
            self.verify()


if __name__ == "__main__":
    unittest.main()