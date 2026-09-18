#!/usr/bin/env python3
"""Managed Capivara YARA-X ruleset provisioning for Linux Agents."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from security_yarax import managed_binary

RULESET_VERSION = "2026.09.18.1"
RULESET_SHA256 = "954bcffb0528bc21d1422b269b77cdf3e2f6d105c6de7321ff2962de8f926616"
RULESET_CONTENT = """// Capivara DSM managed YARA-X baseline ruleset.
// Version: 2026.09.18.1
//
// This initial baseline contains a deterministic EICAR validation signature.
// Curated production signatures are versioned independently and will be
// distributed through the Controller security management plane.

rule Capivara_EICAR_Test_File : block malware test
{
    meta:
        description = "EICAR anti-malware test file"
        source = "Capivara DSM baseline"
        ruleset_version = "2026.09.18.1"

    strings:
        $eicar = "X5O!P%@AP[4\\\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*" ascii

    condition:
        $eicar
}
"""
STATE_ROOT = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
RULESET_ROOT = STATE_ROOT / "security" / "yara-x" / "rulesets"
CURRENT = RULESET_ROOT / "current.json"


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_current() -> dict[str, Any] | None:
    try:
        value = json.loads(CURRENT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def managed_rules_path() -> str | None:
    current = _read_current()
    if not current:
        return None
    if str(current.get("version") or "") != RULESET_VERSION:
        return None
    if str(current.get("sha256") or "").lower() != RULESET_SHA256:
        return None
    raw = str(current.get("rules_path") or "").strip()
    if not raw:
        return None
    path = Path(raw)
    try:
        path.resolve().relative_to(RULESET_ROOT.resolve())
    except (OSError, ValueError):
        return None
    if not path.is_file() or path.is_symlink():
        return None
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None
    return str(path) if digest == RULESET_SHA256 else None


def _validate_rules(binary: Path, rules: Path) -> None:
    if not binary.is_file():
        raise RuntimeError("YARA-X engine is unavailable; install engine first")
    if not rules.is_file() or rules.is_symlink():
        raise RuntimeError("YARA-X ruleset candidate is unavailable")
    with tempfile.TemporaryDirectory(prefix=".yarax-rules-validate-", dir=str(RULESET_ROOT)) as td:
        target = Path(td) / "empty.bin"
        target.write_bytes(b"")
        completed = subprocess.run(
            [
                str(binary),
                "scan",
                "--output-format=ndjson",
                "--timeout",
                "15",
                str(rules),
                str(target),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
            check=False,
        )
        if completed.returncode != 0:
            output = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(
                f"YARA-X ruleset validation failed with exit code {completed.returncode}: {output[-1000:]}"
            )


def status() -> dict[str, Any]:
    current = _read_current() or {}
    path = managed_rules_path()
    checksum = None
    valid_checksum = False
    if path:
        try:
            checksum = hashlib.sha256(Path(path).read_bytes()).hexdigest()
            valid_checksum = checksum == RULESET_SHA256 and str(current.get("sha256") or "").lower() == RULESET_SHA256
        except OSError:
            pass
    return {
        "engine": "yara-x",
        "managed": True,
        "platform": "linux",
        "ruleset_version": current.get("version"),
        "pinned_ruleset_version": RULESET_VERSION,
        "path": path,
        "installed": bool(path),
        "sha256": checksum,
        "expected_sha256": current.get("sha256"),
        "checksum_valid": bool(path and valid_checksum),
        "rules_count": 1 if path else 0,
        "state": "ready" if path and valid_checksum else "error" if path else "missing",
    }


def install() -> dict[str, Any]:
    payload = RULESET_CONTENT.encode("utf-8")
    digest = _digest_bytes(payload)
    if digest != RULESET_SHA256:
        raise RuntimeError("Bundled YARA-X ruleset checksum mismatch")

    binary_raw = managed_binary()
    if not binary_raw:
        raise RuntimeError("YARA-X engine is unavailable; install engine first")
    binary = Path(binary_raw)

    version_root = RULESET_ROOT / "versions" / RULESET_VERSION
    final_rules = version_root / "baseline.yar"
    if final_rules.is_file():
        if hashlib.sha256(final_rules.read_bytes()).hexdigest() != RULESET_SHA256:
            raise RuntimeError("Installed YARA-X ruleset checksum mismatch")
        _validate_rules(binary, final_rules)
        return _activate(final_rules)

    RULESET_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".yarax-rules-", dir=str(RULESET_ROOT)) as td:
        temporary = Path(td)
        candidate = temporary / "baseline.yar"
        candidate.write_bytes(payload)
        if hashlib.sha256(candidate.read_bytes()).hexdigest() != RULESET_SHA256:
            raise RuntimeError("YARA-X ruleset staging checksum mismatch")
        _validate_rules(binary, candidate)

        staged_version = temporary / "version"
        staged_version.mkdir()
        staged_rules = staged_version / "baseline.yar"
        staged_rules.write_bytes(candidate.read_bytes())
        _validate_rules(binary, staged_rules)

        version_root.parent.mkdir(parents=True, exist_ok=True)
        if not version_root.exists():
            os.replace(staged_version, version_root)

    if hashlib.sha256(final_rules.read_bytes()).hexdigest() != RULESET_SHA256:
        raise RuntimeError("Installed YARA-X ruleset checksum mismatch")
    _validate_rules(binary, final_rules)
    return _activate(final_rules)


def _activate(rules: Path) -> dict[str, Any]:
    rules = rules.resolve()
    rules.relative_to(RULESET_ROOT.resolve())
    digest = hashlib.sha256(rules.read_bytes()).hexdigest()
    if digest != RULESET_SHA256:
        raise RuntimeError("YARA-X ruleset checksum mismatch during activation")
    binary_raw = managed_binary()
    if not binary_raw:
        raise RuntimeError("YARA-X engine is unavailable; install engine first")
    _validate_rules(Path(binary_raw), rules)
    payload = {
        "schema_version": 1,
        "engine": "yara-x",
        "version": RULESET_VERSION,
        "rules_path": str(rules),
        "sha256": RULESET_SHA256,
        "rules_count": 1,
    }
    RULESET_ROOT.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".current-", suffix=".json", dir=str(RULESET_ROOT))
    os.close(fd)
    temp = Path(temp_name)
    try:
        temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temp, CURRENT)
    finally:
        temp.unlink(missing_ok=True)
    return status()


__all__ = [
    "RULESET_SHA256",
    "RULESET_VERSION",
    "install",
    "managed_rules_path",
    "status",
]
