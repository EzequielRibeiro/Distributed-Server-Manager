#!/usr/bin/env python3
"""Isolated #928 fixture HMAC attestation, NOT production release signing.

The 32-byte key and private seal live OUTSIDE the installed/candidate payload
trees. The disposable test harness models independent artifact identity and
detects payload/mode changes before backup or file swap. The fixture operator
can recreate its own key, so this can never authorize a real DSM release.
"""
from __future__ import annotations

from importlib.machinery import SourceFileLoader
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import secrets
import stat
import tempfile

_KEY = ".dsm928-fixture-signer.key"
_SEAL = ".dsm928-fixture-package-seal.json"
_KIND = "DSM928DisposablePackageAttestation"


class FixturePackageError(RuntimeError):
    pass


def _private_root(path: Path) -> Path:
    root = Path(path)
    try:
        resolved = root.resolve(strict=True)
        tmp = Path(tempfile.gettempdir()).resolve(strict=True)
        if (root.is_symlink() or resolved == tmp or tmp not in resolved.parents
                or not root.is_dir() or root.stat().st_uid != os.geteuid()
                or root.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO)):
            raise ValueError("unsafe private fixture workspace")
        marker = root / "fixture-owner"
        if (marker.is_symlink() or marker.read_bytes()
                != b"DSM928_DISPOSABLE_FIXTURE_V1\n"):
            raise ValueError("invalid disposable fixture marker")
    except (OSError, ValueError) as exc:
        raise FixturePackageError("not a private owner-marked disposable fixture") from exc
    return resolved


def _private_file(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise FixturePackageError("attestation file missing or symlinked")
    identity = path.stat()
    if (identity.st_uid != os.geteuid() or identity.st_mode & 0o077
            or not stat.S_ISREG(identity.st_mode)):
        raise FixturePackageError("untrusted attestation file permissions or owner")
    return path.read_bytes()


def _plan():
    path = Path(__file__).with_name("game-uptime-plan.py")
    loader = SourceFileLoader("dsm928_fixture_seal_inventory", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    result = importlib.util.module_from_spec(spec)
    loader.exec_module(result)
    return result


def _tree_digest(path: Path) -> str:
    inventory = _plan()._inventory(path)
    data = {name: [mode, digest] for name, (mode, digest) in sorted(inventory.items())}
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _body(root: Path, *, nonce: str) -> dict:
    installed, candidate = root / "installed", root / "new-payload"
    try:
        old_version = (installed / "version").read_text().strip()
        new_version = (candidate / "version").read_text().strip()
        if not old_version or not new_version:
            raise ValueError("empty release version")
        return {
            "kind": _KIND, "schema_version": 1,
            "scope": "disposable_only_not_production",
            "nonce": nonce, "installed_version": old_version,
            "candidate_version": new_version,
            "installed_tree_sha256": _tree_digest(installed),
            "candidate_tree_sha256": _tree_digest(candidate),
            "live_no_drain_authorized": False,
        }
    except (OSError, ValueError) as exc:
        raise FixturePackageError("could not attest the complete fixture release") from exc


def _canonical(body: dict) -> bytes:
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def seal_test_fixture(root: Path) -> dict:
    """Test setup only: issuer key is generated outside candidate payload."""
    root = _private_root(root)
    key_file, seal_file = root / _KEY, root / _SEAL
    if key_file.exists() or key_file.is_symlink():
        key = _private_file(key_file)
    else:
        key = secrets.token_bytes(32)
        with key_file.open("xb") as stream:
            stream.write(key)
        key_file.chmod(0o600)
    if len(key) != 32:
        raise FixturePackageError("invalid fixture attestation key")
    body = _body(root, nonce=secrets.token_hex(16))
    issued = {**body, "hmac_sha256": hmac.new(key, _canonical(body),
                                             hashlib.sha256).hexdigest()}
    if seal_file.is_symlink():
        raise FixturePackageError("symlinked fixture seal")
    seal_file.write_text(json.dumps(issued, sort_keys=True) + "\n", encoding="utf-8")
    seal_file.chmod(0o600)
    return issued


def verify_fixture_attestation(root: Path) -> dict:
    """Never accepts a non-disposable payload or grants production authority."""
    root = _private_root(root)
    key = _private_file(root / _KEY)
    if len(key) != 32:
        raise FixturePackageError("missing valid independent test issuer key")
    try:
        signed = json.loads(_private_file(root / _SEAL))
        if not isinstance(signed, dict):
            raise ValueError("invalid fixture seal")
        mac = signed.pop("hmac_sha256")
        if (not isinstance(mac, str) or len(mac) != 64
                or not hmac.compare_digest(
                    mac, hmac.new(key, _canonical(signed), hashlib.sha256).hexdigest())):
            raise ValueError("signature mismatch")
        if (signed.get("kind") != _KIND or signed.get("schema_version") != 1
                or signed.get("scope") != "disposable_only_not_production"
                or signed.get("live_no_drain_authorized") is not False
                or set(signed) != {
                    "kind", "schema_version", "scope", "nonce", "installed_version",
                    "candidate_version", "installed_tree_sha256",
                    "candidate_tree_sha256", "live_no_drain_authorized"}
                or not isinstance(signed.get("nonce"), str)
                or len(signed["nonce"]) != 32
                or _body(root, nonce=signed["nonce"]) != signed):
            raise ValueError("payload changed or seal contract violated")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise FixturePackageError("disposable package attestation invalid") from exc
    return {
        "kind": _KIND,
        "scope": "disposable_only_not_production",
        "verified": True,
        "candidate_tree_sha256": signed["candidate_tree_sha256"],
        "live_no_drain_authorized": False,
    }
