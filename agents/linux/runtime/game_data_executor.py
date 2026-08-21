#!/usr/bin/env python3
"""Execute one resolved game-data selection locally on a Linux Agent."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from typing import Any
import urllib.request
import zipfile

from game_data_state import GAME_DATA_ROOT, record_game_data, write_json


def _write_result(path: Path, payload: dict[str, Any]) -> None:
    write_json(path, payload)


def _safe_name(value: Any, label: str) -> str:
    text = str(value or "").strip()
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    if not text or any(ch not in allowed for ch in text):
        raise ValueError(f"invalid {label}")
    return text


def _target_for(selection: dict[str, Any]) -> Path:
    game = _safe_name(selection.get("game"), "game")
    declared = Path(str(selection.get("install_dir") or "serverfiles"))
    leaf = declared.name if declared.name not in {"", ".", "/"} else "serverfiles"
    leaf = _safe_name(leaf, "install target")
    target = (GAME_DATA_ROOT / game / leaf).resolve()
    target.relative_to(GAME_DATA_ROOT)
    return target


def _steamcmd() -> str:
    for candidate in (shutil.which("steamcmd"), "/usr/games/steamcmd"):
        if candidate and Path(candidate).is_file():
            return str(candidate)
    raise RuntimeError("SteamCMD is not available on this Agent")


def _run_steam(selection: dict[str, Any], target: Path) -> None:
    install = selection.get("install") if isinstance(selection.get("install"), dict) else {}
    app_id = str(install.get("package_id") or "").strip()
    if not app_id.isdigit():
        raise ValueError("Steam package_id is missing or invalid")
    auth = str(selection.get("auth") or "anonymous").strip().lower()
    if auth == "anonymous":
        login = "anonymous"
    else:
        login = str(os.environ.get("DSM_STEAM_USER") or "").strip()
        if not login:
            raise RuntimeError(
                "Steam authentication is required on this Agent; "
                "configure DSM_STEAM_USER and authenticate SteamCMD locally"
            )

    target.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            _steamcmd(),
            "+force_install_dir",
            str(target),
            "+login",
            login,
            "+app_update",
            app_id,
            "validate",
            "+quit",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=7200,
        check=False,
        env={**os.environ, "HOME": os.environ.get("HOME", "/var/lib/capivara-agent")},
    )
    output = completed.stdout or ""
    print(output, end="" if output.endswith("\n") else "\n", flush=True)
    if completed.returncode != 0:
        lowered = output.lower()
        if "password" in lowered or "steam guard" in lowered or "two-factor" in lowered:
            raise RuntimeError("Steam authentication is required or expired on this Agent")
        raise RuntimeError(f"SteamCMD failed with exit code {completed.returncode}")


def _download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "Capivara-Agent/1"})
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output, length=1024 * 1024)


def _verify_sha256(path: Path, expected: str | None) -> None:
    expected = str(expected or "").strip().lower()
    if not expected:
        return
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest().lower() != expected:
        raise RuntimeError("download checksum mismatch")


def _safe_member(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise RuntimeError("unsafe archive member")
    return path


def _extract_zip(archive: Path, target: Path) -> None:
    with zipfile.ZipFile(archive) as package:
        for info in package.infolist():
            _safe_member(info.filename)
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise RuntimeError("archive links are not allowed")
        package.extractall(target)


def _extract_tar(archive: Path, target: Path) -> None:
    with tarfile.open(archive, "r:*") as package:
        members = package.getmembers()
        for member in members:
            _safe_member(member.name)
            if not (member.isfile() or member.isdir()):
                raise RuntimeError("unsupported archive member")
        package.extractall(target, members=members)


def _run_http(selection: dict[str, Any], target: Path) -> None:
    install = selection.get("install") if isinstance(selection.get("install"), dict) else {}
    asset = selection.get("asset") if isinstance(selection.get("asset"), dict) else {}
    url = str(asset.get("url") or install.get("url") or "").strip()
    if not (url.startswith("https://") or url.startswith("http://")):
        raise ValueError("HTTP artifact URL is missing or invalid")
    expected = asset.get("sha256") or install.get("sha256")
    archive = selection.get("archive") if isinstance(selection.get("archive"), dict) else {}
    archive_type = str(archive.get("type") or install.get("archive_type") or "")
    target.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="capivara-game-data-") as temporary:
        temp = Path(temporary)
        artifact = temp / "artifact"
        _download(url, artifact)
        _verify_sha256(artifact, expected)
        if archive_type or zipfile.is_zipfile(artifact) or tarfile.is_tarfile(artifact):
            staging = temp / "extract"
            staging.mkdir()
            if zipfile.is_zipfile(artifact):
                _extract_zip(artifact, staging)
            elif tarfile.is_tarfile(artifact):
                _extract_tar(artifact, staging)
            else:
                raise RuntimeError(f"unsupported archive type: {archive_type}")
            for entry in staging.iterdir():
                destination = target / entry.name
                if destination.exists():
                    if destination.is_dir():
                        shutil.rmtree(destination)
                    else:
                        destination.unlink()
                shutil.move(str(entry), str(destination))
        else:
            raw_name = asset.get("name") or install.get("asset") or selection.get("executable") or "artifact"
            filename = _safe_name(Path(str(raw_name)).name, "artifact filename")
            destination = target / filename
            shutil.copy2(artifact, destination)
            if str(selection.get("executable") or "") == filename:
                destination.chmod(destination.stat().st_mode | 0o111)


def _execute(command: dict[str, Any]) -> dict[str, Any]:
    action = str(command.get("action") or "install").lower()
    selection = command.get("selection")
    if not isinstance(selection, dict):
        raise ValueError("runtime selection is missing")
    target = _target_for(selection)
    provider = str(selection.get("provider") or "").strip().lower()

    if action == "verify":
        if not target.is_dir() or not any(target.iterdir()):
            raise RuntimeError("game-data is not installed")
    elif action in {"install", "update"}:
        if provider == "steam":
            _run_steam(selection, target)
        elif provider in {"http", "http-archive", "github"}:
            _run_http(selection, target)
        else:
            raise RuntimeError(f"provider not supported by standalone Linux Agent: {provider}")
    else:
        raise ValueError("unsupported game-data action")

    return {
        "provider": provider,
        "game": selection.get("game"),
        "version": selection.get("version"),
        "target_path": str(target),
    }


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: game_data_executor.py REQUEST RESULT", file=sys.stderr)
        return 2
    request_path = Path(sys.argv[1])
    result_path = Path(sys.argv[2])
    command = json.loads(request_path.read_text(encoding="utf-8"))
    job_id = str(command.get("job_id") or "").strip()
    action = str(command.get("action") or "install").strip().lower()
    selection = command.get("selection") if isinstance(command.get("selection"), dict) else {}
    _write_result(result_path, {"job_id": job_id, "status": "running", "progress": 5})
    try:
        detail = _execute(command)
    except Exception as exc:
        _write_result(
            result_path,
            {"job_id": job_id, "status": "failed", "progress": 100, "error": str(exc)[:2000]},
        )
        print(f"game-data job failed: {exc}", file=sys.stderr, flush=True)
        return 1
    completed = {"job_id": job_id, "status": "completed", "progress": 100, **detail}
    _write_result(result_path, completed)
    try:
        record_game_data(job_id=job_id, action=action, selection=selection, result=completed)
    except Exception as exc:
        print(f"game-data inventory warning: {exc}", file=sys.stderr, flush=True)
    print(f"game-data job completed: {job_id}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
