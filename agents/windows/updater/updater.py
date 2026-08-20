#!/usr/bin/env python3
"""Windows Agent self-updater using immutable GitHub Release packages."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

PROGRAM_DATA = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
PROGRAM_FILES = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
STATE_DIR = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", PROGRAM_DATA / "CapivaraAgent" / "state"))
INSTALL_ROOT = Path(os.environ.get("CAPIVARA_AGENT_ROOT", PROGRAM_FILES / "CapivaraAgent"))
REQUEST_PATH = STATE_DIR / "update-request.json"
RESULT_PATH = STATE_DIR / "update-result.json"
REPOSITORY = os.environ.get("CAPIVARA_AGENT_GITHUB_REPOSITORY", "EzequielRibeiro/Distributed-Server-Manager")
TASK_NAME = os.environ.get("CAPIVARA_AGENT_TASK_NAME", "CapivaraAgent")


def _write_result(status: str, **extra) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    temp = RESULT_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps({"status": status, **extra}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(RESULT_PATH)


def _download(url: str, target: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "Capivara-Agent-Windows-Updater"})
    with urllib.request.urlopen(request, timeout=60) as response, target.open("wb") as output:
        shutil.copyfileobj(response, output)


def _safe_extract(package: zipfile.ZipFile, destination: Path) -> None:
    for info in package.infolist():
        raw = info.filename
        name = PurePosixPath(raw)
        if name.is_absolute() or ".." in name.parts or "\\" in raw or ":" in raw:
            raise RuntimeError(f"unsafe archive path: {raw}")
        target = destination.joinpath(*name.parts)
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with package.open(info) as source, target.open("wb") as output:
            shutil.copyfileobj(source, output)


def _verify(package_root: Path, version: str) -> None:
    manifest = json.loads((package_root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("kind") != "CapivaraAgentPackage" or manifest.get("platform") != "windows":
        raise RuntimeError("invalid Windows Agent package")
    if str(manifest.get("version")) != version:
        raise RuntimeError("package version mismatch")
    for relative in manifest.get("required_files", []):
        path = package_root / relative
        expected = ((manifest.get("files") or {}).get(relative) or {}).get("sha256")
        if not path.is_file() or not expected:
            raise RuntimeError(f"invalid package file: {relative}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"internal checksum mismatch: {relative}")


def apply_request() -> int:
    request = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    version = str(request.get("desired_version", "")).strip()
    channel = str(request.get("channel", "stable")).strip().lower()
    if not version:
        raise RuntimeError("desired_version is required")
    if channel == "local/manual":
        raise RuntimeError("local/manual update requires an administrator supplied package")

    tag = version if version.startswith("v") else f"v{version}"
    plain = version[1:] if version.startswith("v") else version
    archive_name = f"capivara-agent-windows-{plain}.zip"
    base = f"https://github.com/{REPOSITORY}/releases/download/{tag}"
    with tempfile.TemporaryDirectory(prefix="capivara-agent-win-update-") as tmp:
        work = Path(tmp)
        archive = work / archive_name
        checksum = work / f"{archive_name}.sha256"
        _download(f"{base}/{archive_name}", archive)
        _download(f"{base}/{archive_name}.sha256", checksum)
        expected = checksum.read_text(encoding="utf-8").split()[0].strip().lower()
        if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
            raise RuntimeError("release checksum mismatch")
        extract = work / "extract"
        extract.mkdir()
        with zipfile.ZipFile(archive) as package:
            _safe_extract(package, extract)
        package_root = extract / f"capivara-agent-windows-{plain}"
        _verify(package_root, plain)
        for relative in (
            "agent/runtime/agent.py",
            "agent/runtime/capabilities.py",
            "agent/runtime/network_inventory.py",
            "agent/runtime/update_client.py",
            "agent/updater/updater.py",
            "agent/common/identity.py",
            "manifest.json",
            "VERSION",
        ):
            source = package_root / relative
            if relative.startswith("agent/runtime/"):
                destination = INSTALL_ROOT / "runtime" / Path(relative).name
            elif relative.startswith("agent/updater/"):
                destination = INSTALL_ROOT / "updater" / Path(relative).name
            elif relative.startswith("agent/common/"):
                destination = INSTALL_ROOT / "common" / Path(relative).name
            else:
                destination = INSTALL_ROOT / Path(relative).name
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(destination.suffix + ".new")
            shutil.copy2(source, temporary)
            os.replace(temporary, destination)

    REQUEST_PATH.unlink(missing_ok=True)
    _write_result("applied", installed_version=plain, rollout_id=request.get("rollout_id"))
    time.sleep(2)
    subprocess.run(["schtasks", "/Run", "/TN", TASK_NAME], check=False, capture_output=True)
    return 0


def main() -> int:
    try:
        return apply_request()
    except Exception as exc:
        REQUEST_PATH.unlink(missing_ok=True)
        _write_result("failed", error=str(exc)[:2000])
        subprocess.run(["schtasks", "/Run", "/TN", TASK_NAME], check=False, capture_output=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
