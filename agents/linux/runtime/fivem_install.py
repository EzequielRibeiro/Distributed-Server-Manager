#!/usr/bin/env python3
"""Typed FiveM/FXServer installer for the Linux Agent.

Installs the current Cfx.re recommended Linux artifact plus the canonical
cfx-server-data tree without exposing arbitrary shell execution.
"""
from __future__ import annotations

import html
import re
import shutil
import stat
import tarfile
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath

_ARTIFACT_INDEX = "https://runtime.fivem.net/artifacts/fivem/build_proot_linux/master/"
_SERVER_DATA = "https://codeload.github.com/citizenfx/cfx-server-data/tar.gz/refs/heads/master"
_MAX_INDEX_BYTES = 2 * 1024 * 1024
_MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024


def _request(url: str):
    return urllib.request.Request(url, headers={"User-Agent": "Capivara-Agent/1"})


def _read_index() -> str:
    with urllib.request.urlopen(_request(_ARTIFACT_INDEX), timeout=30) as response:
        payload = response.read(_MAX_INDEX_BYTES + 1)
    if len(payload) > _MAX_INDEX_BYTES:
        raise RuntimeError("FiveM artifact index is unexpectedly large")
    return payload.decode("utf-8", errors="strict")


def resolve_recommended_artifact(index_html: str | None = None) -> str:
    """Resolve Cfx.re's LATEST RECOMMENDED Linux artifact URL."""
    document = index_html if index_html is not None else _read_index()
    anchors = re.findall(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', document, flags=re.I | re.S)
    for href, body in anchors:
        label = re.sub(r"<[^>]+>", " ", body)
        label = html.unescape(re.sub(r"\s+", " ", label)).strip().upper()
        if "LATEST RECOMMENDED" not in label:
            continue
        resolved = urllib.parse.urljoin(_ARTIFACT_INDEX, html.unescape(href))
        parsed = urllib.parse.urlparse(resolved)
        if parsed.scheme != "https" or parsed.netloc != "runtime.fivem.net":
            raise RuntimeError("FiveM recommended artifact resolved outside runtime.fivem.net")
        if not parsed.path.endswith("/fx.tar.xz"):
            raise RuntimeError("FiveM recommended artifact has an unexpected filename")
        return resolved
    raise RuntimeError("FiveM LATEST RECOMMENDED Linux artifact was not found")


def _download(url: str, destination: Path) -> None:
    total = 0
    with urllib.request.urlopen(_request(url), timeout=120) as response, destination.open("wb") as output:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_DOWNLOAD_BYTES:
                raise RuntimeError("FiveM download exceeds the allowed size")
            output.write(chunk)


def _safe_member(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise RuntimeError("unsafe FiveM archive member")
    return path


def _extract_tar(archive: Path, destination: Path, *, strip_first: bool = False) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:*") as package:
        for member in package.getmembers():
            original = _safe_member(member.name)
            if not (member.isfile() or member.isdir()):
                raise RuntimeError("unsupported FiveM archive member")
            parts = original.parts[1:] if strip_first else original.parts
            if not parts:
                continue
            relative = PurePosixPath(*parts)
            target = (destination / Path(*relative.parts)).resolve()
            target.relative_to(destination.resolve())
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source = package.extractfile(member)
            if source is None:
                raise RuntimeError("FiveM archive member could not be read")
            with source, target.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            target.chmod(member.mode & 0o777)


def install_fivem(target: Path) -> None:
    """Install FXServer and cfx-server-data into an isolated game-data root."""
    target.mkdir(parents=True, exist_ok=True)
    server = target / "server"
    server_data = target / "server-data"
    with tempfile.TemporaryDirectory(prefix="capivara-fivem-") as temporary:
        temp = Path(temporary)
        artifact = temp / "fx.tar.xz"
        data_archive = temp / "cfx-server-data.tar.gz"
        _download(resolve_recommended_artifact(), artifact)
        _download(_SERVER_DATA, data_archive)

        staged_server = temp / "server"
        staged_data = temp / "server-data"
        _extract_tar(artifact, staged_server)
        _extract_tar(data_archive, staged_data, strip_first=True)
        if not (staged_server / "run.sh").is_file():
            raise RuntimeError("FiveM artifact did not provide run.sh")
        if not (staged_data / "resources").is_dir():
            raise RuntimeError("cfx-server-data did not provide resources")

        if server.exists():
            shutil.rmtree(server)
        if server_data.exists():
            shutil.rmtree(server_data)
        shutil.move(str(staged_server), str(server))
        shutil.move(str(staged_data), str(server_data))
        launcher = server / "run.sh"
        launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


__all__ = ["install_fivem", "resolve_recommended_artifact"]
