#!/usr/bin/env python3
"""Read-only, pinned integrity proof for a DSM release archive (#928).

A SHA-256 supplied alongside an untrusted download is NOT an origin proof.
The caller MUST independently trust the exact SHA-256 and commit pins.
This module neither signs releases nor grants live no-drain authorization.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tarfile

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}\Z")


class ReleaseIntegrityError(ValueError):
    """Missing/ambiguous/modified bytes or mismatch with a caller-supplied pin."""


def _unique_json(data: bytes) -> dict:
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ReleaseIntegrityError("duplicate release manifest JSON key")
            result[key] = value
        return result

    try:
        result = json.loads(data.decode("utf-8"), object_pairs_hook=unique_pairs)
    except (ValueError, UnicodeError) as exc:
        raise ReleaseIntegrityError("release manifest is not unambiguous JSON") from exc
    if not isinstance(result, dict):
        raise ReleaseIntegrityError("release manifest must be an object")
    return result


def verify_pinned_archive(
    archive: Path, *, expected_sha256: str,
    expected_git_commit: str, expected_version: str,
) -> dict[str, object]:
    """Verify an immutable input against out-of-band trusted checksum/commit pins.

    Does not consult GitHub, trust a neighboring .sha256, or mutate the archive.
    The report deliberately cannot satisfy a release signature or quiescence gate.
    """
    if (type(expected_sha256) is not str or not _SHA.fullmatch(expected_sha256)
            or type(expected_git_commit) is not str
            or not _COMMIT.fullmatch(expected_git_commit)
            or type(expected_version) is not str
            or not _VERSION.fullmatch(expected_version)):
        raise ReleaseIntegrityError("trusted checksum, commit and version pins are required")
    archive = Path(archive)
    root = "capivara-dsm-" + expected_version
    if archive.name != root + ".tar.gz":
        raise ReleaseIntegrityError("archive filename does not match trusted version")
    try:
        file_info = archive.lstat()
        if not stat.S_ISREG(file_info.st_mode) or file_info.st_nlink != 1:
            raise ReleaseIntegrityError("release archive is not a standalone regular file")
        with archive.open("rb") as handle:
            before = os.fstat(handle.fileno())
            digest = hashlib.sha256()
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
            if digest.hexdigest() != expected_sha256:
                raise ReleaseIntegrityError("release bytes do not match trusted SHA-256 pin")
            handle.seek(0)
            with tarfile.open(fileobj=handle, mode="r:gz") as package:
                members = package.getmembers()
                if not members or len(members) > 100000:
                    raise ReleaseIntegrityError("release archive member count is invalid")
                names: set[str] = set()
                files: dict[str, tarfile.TarInfo] = {}
                for member in members:
                    name = member.name.rstrip("/")
                    pieces = name.split("/")
                    if (name.startswith("/") or any(part in ("", ".", "..")
                                                   for part in pieces)
                            or (name != root and not name.startswith(root + "/"))):
                        raise ReleaseIntegrityError("release archive contains unsafe path")
                    if name in names:
                        raise ReleaseIntegrityError("release archive contains duplicate member")
                    names.add(name)
                    if not (member.isfile() or member.isdir()):
                        raise ReleaseIntegrityError("release archive contains links or special files")
                    if member.isfile():
                        files[name] = member
                manifest_name = root + "/release-manifest.json"
                manifest_entry = files.get(manifest_name)
                if manifest_entry is None or manifest_entry.size > 1024 * 1024:
                    raise ReleaseIntegrityError("release manifest missing or oversized")
                opened = package.extractfile(manifest_entry)
                if opened is None:
                    raise ReleaseIntegrityError("release manifest is unreadable")
                manifest = _unique_json(opened.read())
                required_fields = {
                    "schema_version", "kind", "name", "version", "git_commit",
                    "created_at", "archive", "file_count", "required_files",
                }
                if (set(manifest) != required_fields
                        or type(manifest.get("schema_version")) is not int
                        or manifest["schema_version"] != 1
                        or manifest.get("kind") != "CapivaraReleaseManifest"
                        or manifest.get("name") != "capivara-dsm"
                        or manifest.get("version") != expected_version
                        or manifest.get("git_commit") != expected_git_commit
                        or manifest.get("archive") != archive.name
                        or type(manifest.get("file_count")) is not int
                        or manifest["file_count"] != len(files)
                        or type(manifest.get("created_at")) is not str
                        or not isinstance(manifest.get("required_files"), list)
                        or not manifest["required_files"]):
                    raise ReleaseIntegrityError("release manifest diverges from trusted pins or archive")
                required = manifest["required_files"]
                if (any(type(item) is not str or not item
                        or "/" + item not in ("/" + item)
                        or item.startswith("/")
                        or any(part in ("", ".", "..") for part in item.split("/"))
                        for item in required)
                        or len(set(required)) != len(required)
                        or any(root + "/" + item not in files for item in required)):
                    raise ReleaseIntegrityError("required release files are missing or unsafe")
                version_entry = files.get(root + "/version")
                if version_entry is None or version_entry.size > 256:
                    raise ReleaseIntegrityError("release version file missing or oversized")
                version_file = package.extractfile(version_entry)
                if version_file is None or version_file.read().decode("utf-8").strip() != expected_version:
                    raise ReleaseIntegrityError("release version file differs from manifest")
            after = os.fstat(handle.fileno())
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                    after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
                raise ReleaseIntegrityError("release archive changed during verification")
    except (OSError, tarfile.TarError, UnicodeError) as exc:
        raise ReleaseIntegrityError("release archive cannot be safely verified") from exc

    return {
        "kind": "CapivaraDSMPinnedReleaseIntegrity",
        "schema_version": 1,
        "checksum_matches_trusted_pin": True,
        "manifest_bound_to_commit": True,
        "verified_file_count": len(files),
        # An externally supplied SHA-256 is only an integrity pin; a separate
        # trusted publisher attestation must establish provenance.
        "release_origin_authenticated": False,
        "remote_agent_quiescence_acked": False,
        "external_jobs_acked": False,
        "live_no_drain_authorized": False,
    }
