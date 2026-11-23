#!/usr/bin/env python3
"""#928: production-facing READ-ONLY review of signed no-drain release inputs.

No release enrollment, mutation, Agent ACK, journal creation, or grant occurs
here. A real source of trust is an operator-provisioned root-owned directory
and the independent root-owned publisher key already required by the signed
release verifier. The updater's --no-drain-report calls this through preflight.
"""
from __future__ import annotations

import hashlib
from importlib.machinery import SourceFileLoader
import importlib.util
import os
from pathlib import Path
import re
import stat
import tarfile

REVIEW_DIR = Path("/var/lib/capivara-dsm-928/reviewed-release")
_MARKER = re.compile(r"[0-9a-f]{40}\Z")
_ALLOWED_MANIFEST = re.compile(r"capivara-dsm-[a-zA-Z0-9._+-]+\.manifest\.json\Z")


class OperationalReviewBlocked(RuntimeError):
    pass


def _load(name: str, filename: str):
    loader = SourceFileLoader(name, str(Path(__file__).with_name(filename)))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _trusted_root_dir(path: Path):
    """Refuse replaced, world-writable or non-root-owned trust directories."""
    path = Path(path)
    if not path.is_absolute() or path.is_symlink():
        raise OperationalReviewBlocked("review_directory_not_absolute_or_symlink")
    # /var/lib/capivara-dsm-928 and reviewed-release are deliberately
    # outside /opt/dsm and may NOT be created from this read-only code.
    for current in (path.parent, path):
        try:
            entry = current.lstat()
        except OSError as exc:
            raise OperationalReviewBlocked("review_directory_missing") from exc
        if (not stat.S_ISDIR(entry.st_mode) or entry.st_uid != 0
                or entry.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
            raise OperationalReviewBlocked("review_directory_unsafe")


def _trusted_reviewed_commit(path: Path) -> str:
    try:
        before = path.lstat()
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != 0
                or before.st_nlink != 1 or before.st_size != 41
                or before.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
            raise OperationalReviewBlocked("reviewed_commit_file_untrusted")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_CLOEXEC", 0))
        try:
            after = os.fstat(fd)
            if (before.st_ino, before.st_dev, before.st_size,
                    before.st_mtime_ns) != (
                    after.st_ino, after.st_dev, after.st_size,
                    after.st_mtime_ns):
                raise OperationalReviewBlocked("reviewed_commit_file_changed")
            raw = os.read(fd, 42)
        finally:
            os.close(fd)
        value = raw.decode("ascii").removesuffix("\n")
        if not _MARKER.fullmatch(value):
            raise OperationalReviewBlocked("reviewed_commit_invalid")
        return value
    except (OSError, UnicodeError) as exc:
        raise OperationalReviewBlocked("reviewed_commit_unreadable") from exc


def _target_byte_match(target: Path, archive: Path, root_name: str) -> int:
    """Match every signed TAR file against the proposed installation tree.

    A symlink in the target, modified script or missing file fails closed.
    Existing extra runtime state cannot authenticate a missing archive file.
    """
    if target.is_symlink() or not target.is_dir():
        raise OperationalReviewBlocked("target_tree_untrusted")
    verified = 0
    try:
        with tarfile.open(archive, "r:gz") as package:
            for member in package:
                parts = member.name.rstrip("/").split("/")
                if (not parts or parts[0] != root_name
                        or len(parts) < 1
                        or any(part in ("", ".", "..") for part in parts)):
                    raise OperationalReviewBlocked("unsafe_signed_archive_path")
                if not member.isfile():
                    if not member.isdir():
                        raise OperationalReviewBlocked("archive_not_file_or_directory")
                    continue
                suffix = parts[1:]
                if not suffix:
                    raise OperationalReviewBlocked("archive_root_is_not_a_file")
                candidate = target.joinpath(*suffix)
                if any(item.is_symlink() for item in (
                        target.joinpath(*suffix[:n])
                        for n in range(1, len(suffix) + 1))):
                    raise OperationalReviewBlocked("target_symlink_in_signed_path")
                before = candidate.lstat()
                if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                    raise OperationalReviewBlocked("target_file_missing_or_unsafe")
                signed_file = package.extractfile(member)
                if signed_file is None:
                    raise OperationalReviewBlocked("signed_member_unreadable")
                digest_signed, digest_target = hashlib.sha256(), hashlib.sha256()
                with candidate.open("rb") as current:
                    while True:
                        block = signed_file.read(1024 * 1024)
                        if not block:
                            break
                        digest_signed.update(block)
                    for block in iter(lambda: current.read(1024 * 1024), b""):
                        digest_target.update(block)
                    after = os.fstat(current.fileno())
                if (digest_signed.digest() != digest_target.digest()
                        or before.st_dev != after.st_dev
                        or before.st_ino != after.st_ino
                        or before.st_size != after.st_size
                        or before.st_mtime_ns != after.st_mtime_ns):
                    raise OperationalReviewBlocked("target_differs_from_signed_tar")
                verified += 1
    except (OSError, tarfile.TarError, UnicodeError) as exc:
        raise OperationalReviewBlocked("signed_tree_unreadable") from exc
    if verified == 0:
        raise OperationalReviewBlocked("signed_archive_has_no_files")
    return verified


def evaluate(target: Path, *, review_dir: Path = REVIEW_DIR,
             trusted_inputs_only: bool = True) -> dict:
    """Advisory state: never authorization, even with all signed bytes verified."""
    status = {
        "kind": "DSM928OperationalReleaseReview",
        "mode": "read_only",
        "artifact_origin_verified": False,
        "target_tree_bound_to_signed_tar": False,
        "operational_quiescence_acked": False,
        "external_jobs_acked": False,
        "durable_cross_host_recovery_verified": False,
        "maintenance_hold": {"active": True, "reason": "hold_observation_unavailable"},
        "live_no_drain_authorized": False,
        "blockers": [],
    }
    # Reuse the exact read-only Agent/Worker maintenance hold reader,
    # including its persistent pending journal check across reboot.
    # Missing hold is NOT a quiescence ACK; expired/corrupt hold stays blocked.
    try:
        hold_path = (Path(__file__).resolve().parents[1]
                     / "agents/linux/runtime/game_uptime_maintenance_hold.py")
        loader = SourceFileLoader("dsm928_operational_hold_observation", str(hold_path))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        hold = importlib.util.module_from_spec(spec)
        loader.exec_module(hold)
        observed = hold.observe()
        if (not isinstance(observed, dict)
                or type(observed.get("active")) is not bool):
            raise OperationalReviewBlocked("maintenance_hold_observation_invalid")
        status["maintenance_hold"] = {
            "active": observed["active"],
            "reason": str(observed.get("reason", "unknown"))[:100],
        }
    except (OSError, RuntimeError, ValueError, TypeError):
        status["maintenance_hold"] = {
            "active": True, "reason": "hold_observation_unavailable"}
    if status["maintenance_hold"]["active"]:
        status["blockers"].append("maintenance_or_recovery_hold_requires_review")
    else:
        status["blockers"].append("no_durable_quiescence_hold_established")
    try:
        # Fixtures MUST NOT masquerade as proof that production trust exists.
        if not trusted_inputs_only or Path(review_dir) != REVIEW_DIR:
            raise OperationalReviewBlocked("production_trust_path_is_fixed")
        folder = Path(review_dir)
        _trusted_root_dir(folder)
        reviewed_commit = _trusted_reviewed_commit(folder / "reviewed-commit")
        manifests = [p for p in folder.iterdir()
                     if _ALLOWED_MANIFEST.fullmatch(p.name)]
        if len(manifests) != 1:
            raise OperationalReviewBlocked("exactly_one_reviewed_manifest_required")
        manifest = manifests[0]
        archive = folder / manifest.name.replace(".manifest.json", ".tar.gz")
        statement = folder / manifest.name.replace(".manifest.json", ".provenance.json")
        signature = folder / manifest.name.replace(".manifest.json", ".provenance.sig")
        provenance = _load("dsm928_production_readonly_provenance",
                           "game-uptime-release-provenance.py")
        proof = provenance.verify_signed_release(
            archive, manifest, statement, signature,
            expected_commit=reviewed_commit, disposable_fixture=False)
        if (proof.get("artifact_signature_verified") is not True
                or proof.get("scope") != "root_anchored_release_artifact_only"
                or proof.get("live_no_drain_authorized") is not False):
            raise OperationalReviewBlocked("publisher_verification_failed")
        integrity = _load("dsm928_production_readonly_integrity",
                          "game-uptime-release-integrity.py")
        version = manifest.name.removeprefix("capivara-dsm-").removesuffix(".manifest.json")
        integrity.verify_pinned_archive(
            archive, expected_sha256=proof["artifact_sha256"],
            expected_git_commit=reviewed_commit, expected_version=version)
        status["artifact_origin_verified"] = True
        status["verified_release_commit"] = reviewed_commit
        status["verified_archive_sha256"] = proof["artifact_sha256"]
        status["verified_file_count"] = _target_byte_match(
            Path(target), archive, "capivara-dsm-" + version)
        status["target_tree_bound_to_signed_tar"] = True
    except (OperationalReviewBlocked, ValueError, KeyError, TypeError,
            OSError, RuntimeError) as exc:
        # No operational evidence is ever trusted on a failed verification.
        status["blockers"].append(
            "release_provenance_or_tree_blocked:" + str(exc)[:120])
    # Real Controller/Worker/Agent/external-job acknowledgements MUST be
    # implemented by their owners and persisted with replay-resistant IDs.
    # No synthetic fixture receipt from 2.6 can satisfy these requirements.
    status["blockers"].extend([
        "operational_controller_worker_agent_ack_protocol_not_integrated",
        "external_jobs_quiescence_not_integrated",
        "cross_host_transaction_recovery_not_integrated",
        "updater_no_drain_production_entrypoint_not_authorized",
    ])
    return status
