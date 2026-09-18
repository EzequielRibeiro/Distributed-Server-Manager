#!/usr/bin/env python3
"""Managed YARA-X engine provisioning for Linux Agents and Hybrid runtime."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

VERSION = "1.20.0"
BASE_URL = f"https://github.com/VirusTotal/yara-x/releases/download/v{VERSION}"
ARTIFACTS = {
    "x86_64": {
        "name": f"yara-x-v{VERSION}-x86_64-unknown-linux-gnu.tar.gz",
        "sha256": "cabb8df46492fff59c51261302c71ed9cb2cef393d3f0ca560801a34a8e24cbe",
    },
    "aarch64": {
        "name": f"yara-x-v{VERSION}-aarch64-unknown-linux-gnu.tar.gz",
        "sha256": "c1d6f63a6fe55c17b5ddbfcb89d34599b737226a683ee492b12d92d1d541f304",
    },
}
STATE_ROOT = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
TOOL_ROOT = STATE_ROOT / "tools" / "yara-x"
CURRENT = TOOL_ROOT / "current.json"


def normalize_architecture(value: str | None = None) -> str:
    machine = str(value or platform.machine() or "").strip().lower()
    aliases = {
        "amd64": "x86_64",
        "x86_64": "x86_64",
        "arm64": "aarch64",
        "aarch64": "aarch64",
    }
    return aliases.get(machine, machine or "unknown")


def artifact_spec(architecture: str | None = None) -> dict[str, str]:
    arch = normalize_architecture(architecture)
    spec = ARTIFACTS.get(arch)
    if not spec:
        raise RuntimeError(f"YARA-X unsupported Linux architecture: {arch}")
    return {
        "version": VERSION,
        "architecture": arch,
        "name": spec["name"],
        "sha256": spec["sha256"],
        "url": f"{BASE_URL}/{spec['name']}",
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_extract_tar(archive: Path, target: Path) -> None:
    with tarfile.open(archive, "r:gz") as package:
        members = package.getmembers()
        for member in members:
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts:
                raise RuntimeError("YARA-X archive contains an unsafe path")
            if not (member.isfile() or member.isdir()):
                raise RuntimeError("YARA-X archive contains unsupported entries")
        package.extractall(target, members=members)


def _locate_binary(root: Path) -> Path:
    candidates = []
    for path in root.rglob("yr"):
        try:
            mode = path.lstat().st_mode
        except OSError:
            continue
        if stat.S_ISREG(mode) and not path.is_symlink():
            candidates.append(path)
    if len(candidates) != 1:
        raise RuntimeError("YARA-X archive did not contain exactly one yr executable")
    binary = candidates[0]
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    return binary


def _probe(binary: Path) -> str:
    completed = subprocess.run(
        [str(binary), "--version"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=30,
        check=False,
    )
    output = (completed.stdout or "").strip()
    if completed.returncode != 0:
        raise RuntimeError(f"YARA-X validation failed with exit code {completed.returncode}: {output[-500:]}")
    if VERSION not in output:
        raise RuntimeError(f"YARA-X version mismatch: expected {VERSION}, got {output or 'unknown'}")
    return output[:200]


def _read_current() -> dict[str, Any] | None:
    try:
        value = json.loads(CURRENT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def managed_binary() -> str | None:
    current = _read_current()
    if not current:
        return None
    raw = str(current.get("binary") or "").strip()
    if not raw:
        return None
    binary = Path(raw)
    try:
        binary.resolve().relative_to(TOOL_ROOT.resolve())
    except (OSError, ValueError):
        return None
    return str(binary) if binary.is_file() else None


def status() -> dict[str, Any]:
    current = _read_current() or {}
    binary = managed_binary()
    functional = False
    error = None
    observed = None
    if binary:
        try:
            observed = _probe(Path(binary))
            functional = True
        except Exception as exc:
            error = str(exc)[:1000]
    return {
        "engine": "yara-x",
        "managed": True,
        "platform": "linux",
        "architecture": normalize_architecture(),
        "pinned_version": VERSION,
        "installed_version": current.get("version"),
        "path": binary,
        "installed": bool(binary),
        "functional": functional,
        "state": "ready" if functional else "error" if binary else "missing",
        "observed_version": observed,
        "error": error,
    }


def install() -> dict[str, Any]:
    spec = artifact_spec()
    version_root = TOOL_ROOT / "versions" / VERSION
    existing = version_root / "yr"
    if existing.is_file():
        _probe(existing)
        relative = existing.relative_to(TOOL_ROOT)
        return _activate(relative, spec)

    TOOL_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".yarax-", dir=str(TOOL_ROOT)) as td:
        temporary = Path(td)
        archive = temporary / spec["name"]
        request = urllib.request.Request(spec["url"], headers={"User-Agent": "Capivara-Agent/YARA-X"})
        with urllib.request.urlopen(request, timeout=120) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)

        digest = _sha256(archive)
        if digest.lower() != spec["sha256"].lower():
            raise RuntimeError("YARA-X artifact checksum mismatch")

        extracted = temporary / "extract"
        extracted.mkdir()
        _safe_extract_tar(archive, extracted)
        binary = _locate_binary(extracted)
        observed = _probe(binary)

        staged_version = temporary / "version"
        staged_version.mkdir()
        staged_binary = staged_version / "yr"
        shutil.copy2(binary, staged_binary)
        staged_binary.chmod(staged_binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
        _probe(staged_binary)

        version_root.parent.mkdir(parents=True, exist_ok=True)
        if not version_root.exists():
            os.replace(staged_version, version_root)

    final_binary = version_root / "yr"
    _probe(final_binary)
    result = _activate(final_binary.relative_to(TOOL_ROOT), spec)
    result["observed_version"] = observed
    return result


def _activate(relative_binary: Path, spec: dict[str, str]) -> dict[str, Any]:
    binary = (TOOL_ROOT / relative_binary).resolve()
    binary.relative_to(TOOL_ROOT.resolve())
    observed = _probe(binary)
    payload = {
        "schema_version": 1,
        "engine": "yara-x",
        "version": VERSION,
        "architecture": spec["architecture"],
        "binary": str(binary),
        "sha256": spec["sha256"],
        "artifact": spec["name"],
    }
    TOOL_ROOT.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".current-", suffix=".json", dir=str(TOOL_ROOT))
    os.close(fd)
    temp = Path(temp_name)
    try:
        temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temp, CURRENT)
    finally:
        temp.unlink(missing_ok=True)
    return {**status(), "artifact": spec["name"], "sha256": spec["sha256"], "observed_version": observed}


__all__ = ["VERSION", "artifact_spec", "install", "managed_binary", "normalize_architecture", "status"]
