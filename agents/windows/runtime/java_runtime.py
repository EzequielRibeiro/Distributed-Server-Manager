#!/usr/bin/env python3
"""Discover and select side-by-side Java runtimes on Windows Agents."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable

_JAVA_VERSION = re.compile(r'version\s+"([^"]+)"', re.IGNORECASE)


def java_major(version: str) -> int | None:
    token = str(version or "").strip()
    if not token:
        return None
    parts = token.split(".")
    try:
        return int(parts[1]) if parts[0] == "1" and len(parts) > 1 else int(parts[0])
    except ValueError:
        return None


def _candidate_paths() -> tuple[Path, ...]:
    candidates: list[Path] = []
    default = shutil.which("java.exe") or shutil.which("java")
    if default:
        candidates.append(Path(default))
    java_home = str(os.environ.get("JAVA_HOME") or "").strip()
    if java_home:
        candidates.append(Path(java_home) / "bin" / "java.exe")
    roots = [
        Path(str(os.environ.get("ProgramFiles") or r"C:\Program Files")),
        Path(str(os.environ.get("ProgramW6432") or r"C:\Program Files")),
    ]
    patterns = (
        "Java/*/bin/java.exe",
        "Eclipse Adoptium/*/bin/java.exe",
        "Microsoft/jdk-*/bin/java.exe",
        "Amazon Corretto/jdk*/bin/java.exe",
    )
    for root in roots:
        for pattern in patterns:
            candidates.extend(sorted(root.glob(pattern)))
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        key = str(resolved).lower()
        if key in seen or not resolved.is_file():
            continue
        seen.add(key)
        unique.append(resolved)
    return tuple(unique)


def probe_java(path: str | Path) -> dict[str, Any]:
    executable = str(Path(path))
    result: dict[str, Any] = {"path": executable, "installed": True, "functional": False, "state": "error", "version": None, "major": None}
    try:
        completed = subprocess.run(
            [executable, "-version"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, timeout=15, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        output = completed.stdout or ""
        match = _JAVA_VERSION.search(output)
        version = match.group(1) if match else None
        major = java_major(version or "")
        functional = completed.returncode == 0 and major is not None
        result.update(functional=functional, state="ready" if functional else "error", version=version, major=major)
        if not functional:
            result["error"] = output[-1000:] or f"java -version failed with exit code {completed.returncode}"
    except Exception as exc:
        result["error"] = str(exc)[:1000]
    return result


def discover_java_runtimes(paths: Iterable[str | Path] | None = None) -> list[dict[str, Any]]:
    candidates = tuple(Path(item) for item in paths) if paths is not None else _candidate_paths()
    runtimes: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for candidate in candidates:
        if not candidate.is_file():
            continue
        status = probe_java(candidate)
        if not status.get("functional"):
            continue
        major = int(status["major"])
        path = str(Path(str(status["path"])).resolve())
        key = (major, path.lower())
        if key in seen:
            continue
        seen.add(key)
        status["path"] = path
        runtimes.append(status)
    runtimes.sort(key=lambda item: (int(item.get("major") or 0), str(item.get("path") or "").lower()))
    return runtimes


def compatible_java_runtimes(requirements: dict[str, Any] | None, runtimes: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    source = requirements if isinstance(requirements, dict) else {}
    java = source.get("java") if isinstance(source.get("java"), dict) else source
    try:
        minimum = max(0, int(java.get("min") or 0))
    except (TypeError, ValueError):
        minimum = 0
    try:
        maximum = max(0, int(java.get("max") or 0))
    except (TypeError, ValueError):
        maximum = 0
    result = []
    for runtime in runtimes:
        try:
            major = int(runtime.get("major") or 0)
        except (TypeError, ValueError):
            continue
        if not major or runtime.get("functional") is False:
            continue
        if minimum and major < minimum:
            continue
        if maximum and major > maximum:
            continue
        result.append(dict(runtime))
    return result


def select_java_executable(requirements: dict[str, Any] | None = None, *, runtimes: Iterable[dict[str, Any]] | None = None) -> str:
    discovered = list(runtimes) if runtimes is not None else discover_java_runtimes()
    compatible = compatible_java_runtimes(requirements, discovered)
    if compatible:
        return str(max(compatible, key=lambda item: int(item.get("major") or 0))["path"])
    source = requirements if isinstance(requirements, dict) else {}
    java = source.get("java") if isinstance(source.get("java"), dict) else source
    minimum = java.get("min") if isinstance(java, dict) else None
    maximum = java.get("max") if isinstance(java, dict) else None
    if minimum or maximum:
        raise RuntimeError(f"No compatible Java runtime is available (required {minimum or '*'}..{maximum or '*'})")
    default = shutil.which("java.exe") or shutil.which("java")
    if not default:
        raise RuntimeError("Java is not available on this Agent")
    return str(Path(default).resolve())


__all__ = ["compatible_java_runtimes", "discover_java_runtimes", "java_major", "probe_java", "select_java_executable"]
