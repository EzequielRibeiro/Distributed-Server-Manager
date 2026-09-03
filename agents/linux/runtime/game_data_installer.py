#!/usr/bin/env python3
"""Typed post-download installers for Linux Agent game data.

The contract intentionally does not expose arbitrary shell execution.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

_ALLOWED_TYPES = {"java_jar"}
_ALLOWED_JAVA_ARGS = {"--installServer"}
_MAX_TIMEOUT_SECONDS = 1800
_MAX_EXPECTED_OUTPUTS = 32


def _safe_relative(value: Any, label: str) -> PurePosixPath:
    text = str(value or "").strip().replace("\\", "/")
    path = PurePosixPath(text)
    if not text or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"invalid {label}")
    return path


def _inside(root: Path, relative: PurePosixPath) -> Path:
    candidate = (root / Path(*relative.parts)).resolve()
    candidate.relative_to(root.resolve())
    return candidate


def _installer_artifact(selection: dict[str, Any], installer: dict[str, Any]) -> str:
    explicit = str(installer.get("artifact") or "").strip()
    if explicit:
        return explicit
    asset = selection.get("asset") if isinstance(selection.get("asset"), dict) else {}
    install = selection.get("install") if isinstance(selection.get("install"), dict) else {}
    return str(asset.get("name") or install.get("asset") or "").strip()


def _normalize_launch_args(installer: dict[str, Any], target: Path) -> None:
    launch = installer.get("launch_args")
    if launch is None:
        return
    if not isinstance(launch, dict):
        raise ValueError("installer launch_args must be an object")
    pattern = _safe_relative(launch.get("linux_glob"), "Linux launch args glob").as_posix()
    output = _inside(target, _safe_relative(launch.get("output") or "capivara-launch.args", "launch args output"))
    matches = [path for path in target.glob(pattern) if path.is_file()]
    if len(matches) != 1:
        raise RuntimeError("typed installer did not produce exactly one Linux launch args file")
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(matches[0], output)


def validate_installer(selection: dict[str, Any], target: Path) -> tuple[list[str], int, list[Path], dict[str, Any]] | None:
    installer = selection.get("installer")
    if installer is None:
        return None
    if not isinstance(installer, dict):
        raise ValueError("installer must be an object")
    installer_type = str(installer.get("type") or "").strip()
    if installer_type not in _ALLOWED_TYPES:
        raise ValueError("unsupported installer type")

    artifact_name = _installer_artifact(selection, installer)
    artifact = _inside(target, _safe_relative(artifact_name, "installer artifact"))
    if not artifact.is_file():
        raise RuntimeError("installer artifact is missing")

    args = installer.get("args") or []
    if not isinstance(args, list) or any(str(arg) not in _ALLOWED_JAVA_ARGS for arg in args):
        raise ValueError("installer arguments are not allowed")

    timeout = int(installer.get("timeout_seconds") or 600)
    if timeout < 30 or timeout > _MAX_TIMEOUT_SECONDS:
        raise ValueError("installer timeout is outside allowed bounds")

    expected = installer.get("expected_outputs") or []
    if not isinstance(expected, list) or len(expected) > _MAX_EXPECTED_OUTPUTS:
        raise ValueError("installer expected_outputs are invalid")
    expected_paths = [_inside(target, _safe_relative(item, "expected output")) for item in expected]

    java = shutil.which("java")
    if not java:
        raise RuntimeError("Java is not available on this Agent")
    return [java, "-jar", str(artifact), *[str(arg) for arg in args]], timeout, expected_paths, installer


def execute_installer(selection: dict[str, Any], target: Path) -> None:
    validated = validate_installer(selection, target)
    if validated is None:
        return
    argv, timeout, expected_paths, installer = validated
    completed = subprocess.run(
        argv,
        cwd=str(target),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
        check=False,
        env=dict(os.environ),
    )
    output = completed.stdout or ""
    if output:
        print(output, end="" if output.endswith("\n") else "\n", flush=True)
    if completed.returncode != 0:
        raise RuntimeError(f"typed installer failed with exit code {completed.returncode}")
    _normalize_launch_args(installer, target)
    missing = [path.name for path in expected_paths if not path.exists()]
    if missing:
        raise RuntimeError("typed installer did not produce expected outputs: " + ", ".join(missing))


__all__ = ["execute_installer", "validate_installer"]
