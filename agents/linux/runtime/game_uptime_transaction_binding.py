#!/usr/bin/env python3
"""Read-only root-pinned release identity for DSM #928 remote hold evidence.

This is NOT a release signing authority or a quiescence ACK. An operator/root
coordinator must create the binding independently of /opt/dsm. Without that
binding a remote Agent cannot claim a release-specific no-drain fence.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any

BINDING_PATH = Path("/var/lib/capivara-dsm-928/no-drain-release-binding.json")
_KIND = "CapivaraDSMNoDrainReleaseBinding"
_KEYS = {"kind", "schema_version", "transaction_id", "release_sha256",
         "issued_at", "expires_at", "scope", "live_no_drain_authorized"}
_NONCE = re.compile(r"[0-9a-f]{32}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")


class ReleaseBindingBlocked(RuntimeError):
    pass


def canonical(data: dict[str, Any]) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("ascii") + b"\n"


def _object_unique(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ReleaseBindingBlocked("duplicate_release_binding_key")
        obj[key] = value
    return obj


def validate(data: bytes, *, now: int) -> dict[str, Any]:
    try:
        payload = json.loads(data, object_pairs_hook=_object_unique)
    except (UnicodeError, ValueError, TypeError) as exc:
        raise ReleaseBindingBlocked("invalid_release_binding_json") from exc
    if (not isinstance(payload, dict) or set(payload) != _KEYS
            or canonical(payload) != data
            or payload.get("kind") != _KIND
            or type(payload.get("schema_version")) is not int
            or payload["schema_version"] != 1
            or type(payload.get("transaction_id")) is not str
            or not _NONCE.fullmatch(payload["transaction_id"])
            or type(payload.get("release_sha256")) is not str
            or not _SHA.fullmatch(payload["release_sha256"])
            or type(payload.get("issued_at")) is not int
            or type(payload.get("expires_at")) is not int
            or payload.get("scope") != "root_pinned_release_identity_only"
            or payload.get("live_no_drain_authorized") is not False
            or not (0 < payload["issued_at"] <= now + 30
                    and payload["issued_at"] < payload["expires_at"]
                    <= payload["issued_at"] + 900
                    and now < payload["expires_at"])):
        raise ReleaseBindingBlocked("invalid_or_expired_release_binding")
    return payload


def read_binding(*, path: Path = BINDING_PATH, now: int | None = None,
                 trusted_uid: int = 0) -> dict[str, Any] | None:
    """Read pre-existing root-controlled canonical bytes with O_NOFOLLOW.

    None means absent. Invalid/unsafe/expired content raises, never silently
    accepts a fallback. File must be 0644 so unprivileged Agent can read it.
    Paths other than the fixed production path are fixture-only under /tmp.
    """
    import time
    p = Path(path)
    if p != BINDING_PATH:
        temp = Path(tempfile.gettempdir()).resolve(strict=True)
        if (not p.is_absolute() or temp not in p.parents
                or trusted_uid != os.geteuid()):
            raise ReleaseBindingBlocked("untrusted_binding_path_override")
    elif trusted_uid != 0:
        raise ReleaseBindingBlocked("installed_binding_must_be_root_owned")
    for parent in (p.parent.parent, p.parent):
        try:
            entry = parent.lstat()
        except OSError as exc:
            raise ReleaseBindingBlocked("release_binding_parent_unavailable") from exc
        if (not stat.S_ISDIR(entry.st_mode)
                or entry.st_uid != trusted_uid
                or entry.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
            raise ReleaseBindingBlocked("untrusted_binding_parent")
    try:
        before = p.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ReleaseBindingBlocked("release_binding_unreadable") from exc
    if (not stat.S_ISREG(before.st_mode) or before.st_uid != trusted_uid
            or before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != 0o644
            or not 0 < before.st_size <= 1024):
        raise ReleaseBindingBlocked("untrusted_binding_inode")
    try:
        fd = os.open(p, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_NONBLOCK", 0)
                     | getattr(os, "O_CLOEXEC", 0))
        try:
            actual = os.fstat(fd)
            if (not stat.S_ISREG(actual.st_mode)
                    or (actual.st_dev, actual.st_ino, actual.st_size,
                        actual.st_mtime_ns) != (
                        before.st_dev, before.st_ino, before.st_size,
                        before.st_mtime_ns)
                    or actual.st_uid != trusted_uid
                    or actual.st_nlink != 1
                    or stat.S_IMODE(actual.st_mode) != 0o644):
                raise ReleaseBindingBlocked("release_binding_inode_changed")
            data = os.read(fd, 1025)
            if len(data) != actual.st_size:
                raise ReleaseBindingBlocked("release_binding_read_changed")
        finally:
            os.close(fd)
    except OSError as exc:
        raise ReleaseBindingBlocked("release_binding_open_failed") from exc
    return validate(data, now=int(time.time()) if now is None else now)


def binding_for_hold(hold: dict, *, now: int | None = None,
                     path: Path = BINDING_PATH,
                     trusted_uid: int = 0) -> dict[str, Any] | None:
    """Return release binding only when it exactly matches a trusted hold."""
    from game_uptime_maintenance_hold import observe
    import time
    current = int(time.time()) if now is None else now
    binding = read_binding(path=path, now=current, trusted_uid=trusted_uid)
    if binding is None:
        return None
    if (not isinstance(hold, dict)
            or hold.get("active") is not True
            or hold.get("reason") != "root_owned_maintenance_hold"
            or any(binding[key] != hold.get(key) for key in (
                "transaction_id", "issued_at", "expires_at"))):
        raise ReleaseBindingBlocked("release_binding_hold_mismatch")
    return binding
