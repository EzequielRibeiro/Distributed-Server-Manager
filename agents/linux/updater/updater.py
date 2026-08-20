#!/usr/bin/env python3
"""Privileged, checksum-enforcing Linux Agent updater.

The normal Agent process only writes an update request under /var/lib. This
helper runs as root via a dedicated systemd path/service pair and is the only
component allowed to replace files under /opt/capivara-agent.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

STATE_DIR = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
INSTALL_ROOT = Path(os.environ.get("CAPIVARA_AGENT_ROOT", "/opt/capivara-agent"))
REQUEST_PATH = STATE_DIR / "update-request.json"
RESULT_PATH = STATE_DIR / "update-result.json"
REPOSITORY = os.environ.get("CAPIVARA_AGENT_GITHUB_REPOSITORY", "EzequielRibeiro/Distributed-Server-Manager")


def _write_result(status: str, **extra) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    temp = RESULT_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps({"status": status, **extra}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(RESULT_PATH)


def _download(url: str, path: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "Capivara-Agent-Updater"})
    with urllib.request.urlopen(request, timeout=60) as response, path.open("wb") as output:
        shutil.copyfileobj(response, output)


def _verify_package(package_root: Path, version: str) -> None:
    manifest = json.loads((package_root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("kind") != "CapivaraAgentPackage" or manifest.get("platform") != "linux":
        raise RuntimeError("invalid Linux Agent manifest")
    if str(manifest.get("version")) != version:
        raise RuntimeError("package version mismatch")
    for relative in manifest.get("required_files", []):
        file_path = package_root / relative
        expected = ((manifest.get("files") or {}).get(relative) or {}).get("sha256")
        if not file_path.is_file() or not expected:
            raise RuntimeError(f"invalid package file: {relative}")
        actual = hashlib.sha256(file_path.read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f"internal checksum mismatch: {relative}")


def apply_request() -> int:
    if os.geteuid() != 0:
        raise RuntimeError("Linux Agent updater must run as root")
    request = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    version = str(request.get("desired_version", "")).strip()
    channel = str(request.get("channel", "stable")).strip().lower()
    if not version:
        raise RuntimeError("desired_version is required")
    if channel == "local/manual":
        raise RuntimeError("local/manual updates require administrator supplied package")

    tag = version if version.startswith("v") else f"v{version}"
    plain_version = version[1:] if version.startswith("v") else version
    archive_name = f"capivara-agent-linux-{plain_version}.tar.gz"
    base = f"https://github.com/{REPOSITORY}/releases/download/{tag}"

    with tempfile.TemporaryDirectory(prefix="capivara-agent-update-") as temporary:
        work = Path(temporary)
        archive = work / archive_name
        checksum = work / f"{archive_name}.sha256"
        _download(f"{base}/{archive_name}", archive)
        _download(f"{base}/{archive_name}.sha256", checksum)
        expected = checksum.read_text(encoding="utf-8").split()[0].strip().lower()
        actual = hashlib.sha256(archive.read_bytes()).hexdigest()
        if expected != actual:
            raise RuntimeError("release checksum mismatch")

        extract = work / "extract"
        extract.mkdir()
        with tarfile.open(archive, "r:gz") as package:
            package.extractall(extract, filter="data")
        package_root = extract / f"capivara-agent-linux-{plain_version}"
        _verify_package(package_root, plain_version)

        runtime = package_root / "agent" / "runtime"
        common = package_root / "agent" / "common"
        for source, destination in (
            (runtime / "agent.py", INSTALL_ROOT / "runtime" / "agent.py"),
            (runtime / "capabilities.py", INSTALL_ROOT / "runtime" / "capabilities.py"),
            (runtime / "network_inventory.py", INSTALL_ROOT / "runtime" / "network_inventory.py"),
            (runtime / "update_client.py", INSTALL_ROOT / "runtime" / "update_client.py"),
            (common / "identity.py", INSTALL_ROOT / "common" / "identity.py"),
            (package_root / "manifest.json", INSTALL_ROOT / "manifest.json"),
            (package_root / "VERSION", INSTALL_ROOT / "VERSION"),
        ):
            destination.parent.mkdir(parents=True, exist_ok=True)
            temp = destination.with_suffix(destination.suffix + ".new")
            shutil.copy2(source, temp)
            os.replace(temp, destination)

        new_updater = package_root / "agent" / "updater" / "updater.py"
        if new_updater.is_file():
            destination = INSTALL_ROOT / "updater" / "updater.py"
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(new_updater, destination)

    REQUEST_PATH.unlink(missing_ok=True)
    _write_result("applied", installed_version=plain_version, rollout_id=request.get("rollout_id"))
    subprocess.run(["systemctl", "restart", "capivara-agent.service"], check=False)
    return 0


def main() -> int:
    try:
        return apply_request()
    except Exception as exc:
        REQUEST_PATH.unlink(missing_ok=True)
        _write_result("failed", error=str(exc)[:2000])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
