#!/usr/bin/env python3
"""#928 disposable-only signed approval and multi-actor quiescence fence.

Cryptographic checks are real, but the CI issuer/actors are synthetic.
This is NOT called from production update.sh and NEVER authorizes no-drain.
"""
from __future__ import annotations

import hashlib
import hmac
from importlib.machinery import SourceFileLoader
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import time
from typing import Mapping

_ROLES = ("agent", "controller", "external_jobs", "worker")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_NONCE = re.compile(r"[0-9a-f]{32}\Z")
_MARKER = b"DSM928_DISPOSABLE_FIXTURE_V1\n"


class SecurityFenceError(ValueError):
    pass


def canonical(data: Mapping) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")


def _unique_json(data: bytes) -> dict:
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise SecurityFenceError("ambiguous duplicate JSON key")
            result[key] = value
        return result
    try:
        doc = json.loads(data.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeError, ValueError) as exc:
        raise SecurityFenceError("malformed signed approval") from exc
    if not isinstance(doc, dict) or canonical(doc) != data:
        raise SecurityFenceError("signed approval must be canonical JSON")
    return doc


def _private_workspace(root: Path) -> Path:
    root = Path(root)
    temp = Path(tempfile.gettempdir()).resolve(strict=True)
    if root.is_symlink() or not root.is_dir():
        raise SecurityFenceError("disposable root missing or symlinked")
    real = root.resolve(strict=True)
    stat_info = real.stat()
    if (temp not in real.parents or real == temp
            or stat_info.st_uid != os.geteuid()
            or stat_info.st_mode & (stat.S_IRWXG | stat.S_IRWXO)):
        raise SecurityFenceError("unsafe or nonprivate disposable root")
    marker = real / "fixture-owner"
    if (marker.is_symlink() or not marker.is_file()
            or marker.read_bytes() != _MARKER):
        raise SecurityFenceError("missing disposable owner marker")
    return real


def _read_regular(path: Path, limit: int) -> bytes:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise SecurityFenceError("unsafe or missing signed evidence file")
    info = path.stat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_size <= 0 or info.st_size > limit):
        raise SecurityFenceError("signed evidence has invalid type or size")
    return path.read_bytes()


def _verify_release(archive, sha256, commit, version):
    path = Path(__file__).with_name("game-uptime-release-integrity.py")
    loader = SourceFileLoader("dsm928_signed_release_integrity", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    try:
        return module.verify_pinned_archive(
            archive, expected_sha256=sha256, expected_git_commit=commit,
            expected_version=version)
    except (ValueError, OSError) as exc:
        raise SecurityFenceError("signed release differs from trusted pins") from exc


def verify_disposable_fence(
    workspace: Path, *, archive: Path, release_sha256: str,
    release_commit: str, release_version: str, transaction_id: str,
    approval_file: Path, signature_file: Path, publisher_public_key: Path,
    trusted_publisher_key_sha256: str,
    acknowledgements: list[dict], actor_keys: Mapping[str, bytes],
) -> dict:
    """Atomically seal a ONE-TIME synthetic preflight receipt.

    Caller-supplied trusted key fingerprint MUST be independent of release.
    The receipt is not a remote ACK protocol or a deploy authorization.
    """
    root = _private_workspace(workspace)
    receipt_path = root / "dsm928-security-fence.json"
    if receipt_path.exists() or receipt_path.is_symlink():
        raise SecurityFenceError("replayed or existing transaction fence")
    if (not isinstance(transaction_id, str) or not _NONCE.fullmatch(transaction_id)
            or not isinstance(release_sha256, str) or not _SHA.fullmatch(release_sha256)
            or not isinstance(trusted_publisher_key_sha256, str)
            or not _SHA.fullmatch(trusted_publisher_key_sha256)):
        raise SecurityFenceError("missing independent transaction/release/publisher pins")
    pub = _read_regular(publisher_public_key, 8192)
    approval_bytes = _read_regular(approval_file, 8192)
    sig = _read_regular(signature_file, 128)
    if hashlib.sha256(pub).hexdigest() != trusted_publisher_key_sha256:
        raise SecurityFenceError("untrusted publisher public key")
    if len(sig) != 64:
        raise SecurityFenceError("invalid Ed25519 signature length")
    approval = _unique_json(approval_bytes)
    now = int(time.time())
    fields = {"kind", "schema_version", "scope", "transaction_id", "release_sha256",
              "release_commit", "release_version", "roles", "issued_at", "expires_at"}
    if (set(approval) != fields
            or approval.get("kind") != "DSM928DisposableSignedApproval"
            or type(approval.get("schema_version")) is not int
            or approval["schema_version"] != 1
            or approval.get("scope") != "disposable_only_not_production"
            or approval.get("transaction_id") != transaction_id
            or approval.get("release_sha256") != release_sha256
            or approval.get("release_commit") != release_commit
            or approval.get("release_version") != release_version
            or approval.get("roles") != list(_ROLES)
            or type(approval.get("issued_at")) is not int
            or type(approval.get("expires_at")) is not int
            or not (approval["issued_at"] <= now <= approval["expires_at"]
                    and 0 < approval["expires_at"] - approval["issued_at"] <= 600)):
        raise SecurityFenceError("signed approval scope/identity/expiry mismatch")
    try:
        verified = subprocess.run(
            ("openssl", "pkeyutl", "-verify", "-pubin",
             "-inkey", str(publisher_public_key), "-rawin",
             "-in", str(approval_file), "-sigfile", str(signature_file)),
            check=False, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SecurityFenceError("Ed25519 verification unavailable") from exc
    if verified.returncode != 0:
        raise SecurityFenceError("invalid publisher signature")
    _verify_release(archive, release_sha256, release_commit, release_version)

    if (not isinstance(actor_keys, Mapping) or set(actor_keys) != set(_ROLES)
            or any(type(actor_keys[role]) is not bytes
                   or len(actor_keys[role]) != 32 for role in _ROLES)
            or len(set(actor_keys.values())) != len(_ROLES)):
        raise SecurityFenceError("independent per-actor trust keys required")
    if not isinstance(acknowledgements, list) or len(acknowledgements) != len(_ROLES):
        raise SecurityFenceError("incomplete actor quorum")
    received = set()
    for ack in acknowledgements:
        if not isinstance(ack, dict):
            raise SecurityFenceError("invalid actor ACK")
        role = ack.get("role")
        fields_ack = {"kind", "role", "transaction_id", "release_sha256",
                      "status", "pending_jobs", "hmac_sha256"}
        if (set(ack) != fields_ack or type(role) is not str
                or role not in _ROLES or role in received
                or ack.get("kind") != "DSM928DisposableQuiescenceAck"
                or ack.get("transaction_id") != transaction_id
                or ack.get("release_sha256") != release_sha256
                or ack.get("status") != "quiescent"
                or type(ack.get("pending_jobs")) is not int
                or ack["pending_jobs"] != 0):
            raise SecurityFenceError("missing, stale or nonquiescent actor ACK")
        mac = ack.get("hmac_sha256")
        body = {key: value for key, value in ack.items() if key != "hmac_sha256"}
        good = hmac.new(actor_keys[role], canonical(body), hashlib.sha256).hexdigest()
        if type(mac) is not str or not hmac.compare_digest(mac, good):
            raise SecurityFenceError("actor ACK authentication failed")
        received.add(role)
    if received != set(_ROLES):
        raise SecurityFenceError("actor quorum mismatch")

    # A single fsynced create-without-replace is the durable, anti-replay
    # boundary for one disposable workspace; no automatic crash re-entry.
    report = {
        "kind": "DSM928DisposableSecurityFence",
        "status": "verified_fixture_only", "transaction_id": transaction_id,
        "release_sha256": release_sha256,
        "publisher_signature_verified_under_test_pin": True,
        "fixture_actor_quorum_verified": True, "roles": list(_ROLES),
        "trusted_production_publisher_configured": False,
        "operational_remote_acks_verified": False,
        "live_no_drain_authorized": False,
    }
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(receipt_path, flags, 0o600)
    except FileExistsError as exc:
        raise SecurityFenceError("transaction replay rejected") from exc
    with os.fdopen(fd, "wb") as out:
        out.write(canonical(report) + b"\n")
        out.flush()
        os.fsync(out.fileno())
    dir_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
    return report
