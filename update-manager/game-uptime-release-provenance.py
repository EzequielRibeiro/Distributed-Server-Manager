#!/usr/bin/env python3
"""#928: verify independently signed DSM release bytes, not update permission.

Unlike disposable fixture HMACs, a production release must be signed by a
separately provisioned root-owned public-key trust anchor. This module cannot
install that key, sign releases, stop games, or enable --no-drain. A verified
package is only one prerequisite: distributed quiescence is not implemented.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tarfile
import tempfile

REPOSITORY = "EzequielRibeiro/Distributed-Server-Manager"
TRUST_ANCHOR = Path("/etc/capivara-dsm/release-signing-public.pem")
_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_STATEMENT_KEYS = frozenset({
    "kind", "schema_version", "repository", "git_commit", "version",
    "archive", "archive_sha256", "manifest_sha256",
})


class ReleaseProvenanceBlocked(RuntimeError):
    """A missing, forged, or untrusted artifact cannot advance a transaction."""


def _read_regular(path: Path, maximum: int, *, owner_uid: int | None = None) -> bytes:
    """Read stable regular-file identity without following symlinks."""
    try:
        before = path.lstat()
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_size <= 0 or before.st_size > maximum
                or before.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
                or (owner_uid is not None and before.st_uid != owner_uid)):
            raise ReleaseProvenanceBlocked("untrusted artifact file identity")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_CLOEXEC", 0))
        try:
            current = os.fstat(fd)
            if ((current.st_dev, current.st_ino) !=
                    (before.st_dev, before.st_ino)):
                raise ReleaseProvenanceBlocked("artifact identity changed")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                content = stream.read(maximum + 1)
            after = os.fstat(fd)
            if (len(content) > maximum or len(content) != before.st_size
                    or after.st_size != before.st_size
                    or after.st_mtime_ns != before.st_mtime_ns):
                raise ReleaseProvenanceBlocked("artifact changed during read")
            return content
        finally:
            os.close(fd)
    except OSError as exc:
        raise ReleaseProvenanceBlocked("artifact unreadable") from exc


def _sha256_file(path: Path) -> str:
    try:
        before = path.lstat()
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
            raise ReleaseProvenanceBlocked("untrusted archive")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_CLOEXEC", 0))
        try:
            info = os.fstat(fd)
            if (info.st_dev, info.st_ino) != (before.st_dev, before.st_ino):
                raise ReleaseProvenanceBlocked("archive replaced during read")
            digest = hashlib.sha256()
            with os.fdopen(fd, "rb", closefd=False) as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            after = os.fstat(fd)
            if (before.st_size != after.st_size
                    or before.st_mtime_ns != after.st_mtime_ns):
                raise ReleaseProvenanceBlocked("archive changed during read")
            return digest.hexdigest()
        finally:
            os.close(fd)
    except OSError as exc:
        raise ReleaseProvenanceBlocked("archive unreadable") from exc


def _trusted_public_key(path: Path, *, disposable_fixture: bool) -> bytes:
    if disposable_fixture:
        if path == TRUST_ANCHOR:
            raise ReleaseProvenanceBlocked("fixture must use its own key")
        uid = os.geteuid()
    else:
        if path != TRUST_ANCHOR:
            raise ReleaseProvenanceBlocked("non-root trust anchor forbidden")
        uid = 0
        for parent in (path.parent.parent, path.parent):
            try:
                info = parent.lstat()
            except OSError as exc:
                raise ReleaseProvenanceBlocked("missing root trust directory") from exc
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
                    or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
                raise ReleaseProvenanceBlocked("unsafe root trust directory")
    key = _read_regular(path, 16384, owner_uid=uid)
    if not key.startswith(b"-----BEGIN PUBLIC KEY-----"):
        raise ReleaseProvenanceBlocked("unsupported release trust key")
    return key


def verify_signed_release(
    archive: Path, manifest: Path, statement: Path, signature: Path,
    *, expected_commit: str, trusted_public_key: Path = TRUST_ANCHOR,
    disposable_fixture: bool = False,
) -> dict[str, object]:
    """Verify signed origin AND byte identity; never authorize a DSM update.

    Production mode requires the fixed root-owned out-of-tree trust anchor.
    Test-only key overrides always produce explicitly disposable evidence.
    The expected commit SHA must originate from an independent trusted review.
    No automatic runtime key provisioning or fallback to fixture HMAC exists.
    """
    if type(expected_commit) is not str or not _SHA40.fullmatch(expected_commit):
        raise ReleaseProvenanceBlocked("reviewed commit SHA missing")
    archive, manifest = Path(archive), Path(manifest)
    statement, signature = Path(statement), Path(signature)
    trusted_public_key = Path(trusted_public_key)
    key = _trusted_public_key(
        trusted_public_key, disposable_fixture=disposable_fixture)
    manifest_bytes = _read_regular(manifest, 1024 * 1024)
    statement_bytes = _read_regular(statement, 8192)
    signature_bytes = _read_regular(signature, 8192)
    try:
        release = json.loads(manifest_bytes)
        proof = json.loads(statement_bytes)
        if not isinstance(release, dict) or not isinstance(proof, dict):
            raise ValueError("invalid release objects")
        if (set(proof) != _STATEMENT_KEYS
                or proof["kind"] != "CapivaraDSMReleaseProvenance"
                or type(proof["schema_version"]) is not int
                or proof["schema_version"] != 1
                or proof["repository"] != REPOSITORY
                or proof["git_commit"] != expected_commit
                or release.get("kind") != "CapivaraReleaseManifest"
                or release.get("git_commit") != expected_commit
                or release.get("version") != proof["version"]
                or release.get("archive") != proof["archive"]
                or proof["archive"] != archive.name
                or not isinstance(proof["archive_sha256"], str)
                or not _SHA256.fullmatch(proof["archive_sha256"])
                or not isinstance(proof["manifest_sha256"], str)
                or not _SHA256.fullmatch(proof["manifest_sha256"])):
            raise ValueError("release provenance identity mismatch")
        canonical = (json.dumps(proof, sort_keys=True,
                                separators=(",", ":")) + "\n").encode("utf-8")
        if canonical != statement_bytes:
            raise ValueError("noncanonical signed statement")
        if (hashlib.sha256(manifest_bytes).hexdigest() !=
                proof["manifest_sha256"]):
            raise ValueError("manifest digest mismatch")
        if _sha256_file(archive) != proof["archive_sha256"]:
            raise ValueError("release archive digest mismatch")
        # The signed sidecar must be byte-for-byte the manifest IN the archive.
        name = "capivara-dsm-" + proof["version"] + "/release-manifest.json"
        with tarfile.open(archive, "r:gz") as package:
            matches = [entry for entry in package.getmembers()
                       if entry.name == name]
            if len(matches) != 1 or not matches[0].isfile():
                raise ValueError("release manifest missing or duplicated")
            source = package.extractfile(matches[0])
            if source is None or source.read(1024 * 1024 + 1) != manifest_bytes:
                raise ValueError("archive manifest differs from signed sidecar")
    except (ValueError, KeyError, TypeError, UnicodeError, tarfile.TarError) as exc:
        raise ReleaseProvenanceBlocked("release byte identity not proven") from exc

    # Never execute openssl on mutable source paths: copy verified bytes into
    # an owner-private workspace, so no source symlink swap can affect it.
    with tempfile.TemporaryDirectory(prefix="dsm928-release-verify-") as temp:
        root = Path(temp)
        pub, sig, data = (root / "key.pem", root / "signature.bin",
                          root / "statement.json")
        pub.write_bytes(key)
        sig.write_bytes(signature_bytes)
        data.write_bytes(statement_bytes)
        try:
            result = subprocess.run(
                ("openssl", "dgst", "-sha256", "-verify", str(pub),
                 "-signature", str(sig), str(data)),
                capture_output=True, text=True, check=False, timeout=15,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ReleaseProvenanceBlocked("release signature tool unavailable") from exc
        if result.returncode != 0 or "Verified OK" not in result.stdout:
            raise ReleaseProvenanceBlocked("release signature invalid")
    return {
        "status": "signed_artifact_identity_verified_not_quiesced",
        "scope": ("disposable_fixture_only" if disposable_fixture
                  else "root_anchored_release_artifact_only"),
        "git_commit": expected_commit,
        "artifact_sha256": proof["archive_sha256"],
        "artifact_signature_verified": True,
        "installed_process_identity_verified": False,
        "remote_agent_quiescence_acked": False,
        "external_jobs_acked": False,
        "live_no_drain_authorized": False,
    }
