#!/usr/bin/env python3
"""#928: sign the official DSM release tarball and immutable provenance sidecar.

The signing private key must be supplied out of tree by the release environment.
The trusted public-key fingerprint MUST be pinned independently (for example,
from an operator-approved protected repository environment variable). This
file never generates, exports or provisions signing keys, and never authorizes
a running installation to use --no-drain.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tarfile
import tempfile

_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_SHA64 = re.compile(r"[0-9a-f]{64}\Z")
_REPO = "EzequielRibeiro/Distributed-Server-Manager"


class ReleaseSigningBlocked(RuntimeError):
    pass


def _safe_bytes(path: Path, *, limit: int, private: bool = False) -> bytes:
    path = Path(path)
    try:
        before = path.lstat()
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_size <= 0 or before.st_size > limit
                or before.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
                or (private and stat.S_IMODE(before.st_mode) & 0o077)):
            raise ReleaseSigningBlocked("untrusted_input_file_or_key_permissions")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_CLOEXEC", 0))
        try:
            after = os.fstat(fd)
            if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
                    ) != (before.st_dev, before.st_ino, before.st_size,
                          before.st_mtime_ns):
                raise ReleaseSigningBlocked("input_replaced_during_read")
            data = bytearray()
            while len(data) <= limit:
                b = os.read(fd, min(1024 * 1024, limit + 1 - len(data)))
                if not b:
                    break
                data.extend(b)
            if len(data) != before.st_size:
                raise ReleaseSigningBlocked("input_file_changed_while_reading")
            return bytes(data)
        finally:
            os.close(fd)
    except OSError as exc:
        raise ReleaseSigningBlocked("release_signing_input_unavailable") from exc


def _sha256_file(path: Path) -> str:
    result = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def _openssl(*args: str) -> bytes:
    try:
        proc = subprocess.run(["openssl", *args], capture_output=True,
                              check=False, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ReleaseSigningBlocked("openssl_signer_unavailable") from exc
    if proc.returncode != 0:
        raise ReleaseSigningBlocked("openssl_signer_rejected_input")
    return proc.stdout


def sign_release(*, archive: Path, manifest: Path, commit: str,
                 private_key: Path, trusted_public_key_sha256: str,
                 output_dir: Path) -> dict:
    """Create official provenance sidecars only for a separately pinned key.

    No GitHub publication, deployment, key enrollment or version change.
    The complete signed identity is verified against the archive manifest
    before any output is committed using exclusive creation.
    """
    if (type(commit) is not str or not _SHA40.fullmatch(commit)
            or type(trusted_public_key_sha256) is not str
            or not _SHA64.fullmatch(trusted_public_key_sha256)):
        raise ReleaseSigningBlocked("missing_independent_commit_or_key_pin")
    archive, manifest, private_key, output_dir = map(
        Path, (archive, manifest, private_key, output_dir))
    if (archive.is_symlink() or not archive.is_file()
            or manifest.is_symlink() or manifest.parent != archive.parent
            or output_dir != archive.parent or output_dir.is_symlink()
            or not output_dir.is_dir()):
        raise ReleaseSigningBlocked("release_artifacts_must_share_output_directory")
    key = _safe_bytes(private_key, limit=16384, private=True)
    if not key.startswith(b"-----BEGIN PRIVATE KEY-----"):
        raise ReleaseSigningBlocked("unsupported_private_key_format")
    mbytes = _safe_bytes(manifest, limit=1024*1024)
    try:
        m = json.loads(mbytes)
        version = m["version"]
        if (m["kind"] != "CapivaraReleaseManifest"
                or m["git_commit"] != commit
                or m["archive"] != archive.name
                or archive.name != f"capivara-dsm-{version}.tar.gz"):
            raise ValueError("unmatched release identity")
        with tarfile.open(archive, "r:gz") as tar:
            nodes = [x for x in tar if x.name ==
                     f"capivara-dsm-{version}/release-manifest.json"]
            if len(nodes) != 1 or not nodes[0].isfile():
                raise ValueError("release manifest not in archive")
            reader = tar.extractfile(nodes[0])
            if reader is None or reader.read(1024*1024+1) != mbytes:
                raise ValueError("manifest differs from archive")
    except (KeyError, TypeError, ValueError, tarfile.TarError) as exc:
        raise ReleaseSigningBlocked("manifest_not_bound_to_release") from exc

    prefix = archive.name.removesuffix(".tar.gz")
    statement_path = output_dir / f"{prefix}.provenance.json"
    signature_path = output_dir / f"{prefix}.provenance.sig"
    if (statement_path.exists() or statement_path.is_symlink()
            or signature_path.exists() or signature_path.is_symlink()):
        raise ReleaseSigningBlocked("existing_provenance_requires_manual_review")
    # Snapshot the key in a private workspace; no raw key is exported as
    # output. Extract only a public key for separate-fingerprint comparison.
    with tempfile.TemporaryDirectory(prefix="dsm928-official-signing-") as work:
        temp = Path(work)
        keyfile, pubfile, proof, signature = (
            temp/"key.pem", temp/"public.pem", temp/"statement.json",
            temp/"signature.sig")
        keyfile.write_bytes(key)
        keyfile.chmod(0o600)
        public = _openssl("pkey", "-in", str(keyfile), "-pubout")
        pubfile.write_bytes(public)
        if hashlib.sha256(public).hexdigest() != trusted_public_key_sha256:
            raise ReleaseSigningBlocked("private_key_does_not_match_pinned_publisher")
        statement = {
            "kind": "CapivaraDSMReleaseProvenance",
            "schema_version": 1,
            "repository": _REPO,
            "git_commit": commit,
            "version": version,
            "archive": archive.name,
            "archive_sha256": _sha256_file(archive),
            "manifest_sha256": hashlib.sha256(mbytes).hexdigest(),
        }
        data = (json.dumps(statement, sort_keys=True, separators=(",", ":"))
                + "\n").encode()
        proof.write_bytes(data)
        _openssl("dgst", "-sha256", "-sign", str(keyfile),
                 "-out", str(signature), str(proof))
        _openssl("dgst", "-sha256", "-verify", str(pubfile),
                 "-signature", str(signature), str(proof))
        # Commit the signed statement and signature atomically w.r.t. replay:
        # incomplete output remains present and blocks any blind retry.
        for target, payload in ((statement_path, data),
                                (signature_path, signature.read_bytes())):
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | getattr(os, "O_NOFOLLOW", 0), 0o600)
            try:
                with os.fdopen(fd, "wb") as out:
                    out.write(payload)
                    out.flush()
                    os.fsync(out.fileno())
            except BaseException:
                raise
        dirfd = os.open(output_dir, os.O_RDONLY |
                        getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    return {"status": "official_release_provenance_signed",
            "version": version, "git_commit": commit,
            "archive_sha256": statement["archive_sha256"],
            "publisher_public_key_sha256": trusted_public_key_sha256,
            "live_no_drain_authorized": False,
            "private_key_exported": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--private-key", required=True, type=Path)
    parser.add_argument("--public-key-sha256", required=True)
    args = parser.parse_args()
    try:
        outcome = sign_release(
            archive=args.archive, manifest=args.manifest,
            commit=args.commit, private_key=args.private_key,
            trusted_public_key_sha256=args.public_key_sha256,
            output_dir=args.archive.parent,
        )
    except ReleaseSigningBlocked as exc:
        print(f"Release provenance refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(outcome, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
