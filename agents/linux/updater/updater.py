#!/usr/bin/env python3
"""Privileged, rollback-safe Linux Agent updater."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

STATE_DIR = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
INSTALL_ROOT = Path(os.environ.get("CAPIVARA_AGENT_ROOT", "/opt/capivara-agent"))
CLI_PATH = Path(os.environ.get("CAPIVARA_AGENT_CLI_PATH", "/usr/local/bin/cap"))
POLKIT_RULES_DIR = Path(os.environ.get("CAPIVARA_POLKIT_RULES_DIR", "/etc/polkit-1/rules.d"))
REQUEST_PATH = STATE_DIR / "update-request.json"
RESULT_PATH = STATE_DIR / "update-result.json"
HISTORY_DIR = STATE_DIR / "update-history"
REPOSITORY = os.environ.get("CAPIVARA_AGENT_GITHUB_REPOSITORY", "EzequielRibeiro/Distributed-Server-Manager")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _ensure_state_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if path == STATE_DIR:
        return
    try:
        metadata = STATE_DIR.stat()
        os.chown(path, metadata.st_uid, metadata.st_gid)
        os.chmod(path, 0o700)
    except OSError:
        pass


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    _ensure_state_directory(path.parent)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    try:
        metadata = STATE_DIR.stat()
        os.chown(temp, metadata.st_uid, metadata.st_gid)
    except OSError:
        pass
    os.replace(temp, path)


def _write_result(status: str, **extra: Any) -> dict[str, Any]:
    payload = {"status": status, "generated_at": _utc_now(), **extra}
    _atomic_json(RESULT_PATH, payload)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    _atomic_json(HISTORY_DIR / f"{stamp}.json", payload)
    return payload


def _read_request_summary() -> dict[str, Any]:
    try:
        request = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(request, dict):
        return {}
    return {
        "desired_version": request.get("desired_version"),
        "channel": request.get("channel"),
        "rollout_id": request.get("rollout_id"),
        "batch_number": request.get("batch_number"),
    }


def _download(url: str, path: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "Capivara-Agent-Updater"})
    with urllib.request.urlopen(request, timeout=60) as response, path.open("wb") as output:
        shutil.copyfileobj(response, output)


def _safe_extract(package: tarfile.TarFile, destination: Path) -> None:
    members = []
    for member in package.getmembers():
        name = PurePosixPath(member.name)
        if name.is_absolute() or ".." in name.parts:
            raise RuntimeError(f"unsafe archive path: {member.name}")
        if not (member.isfile() or member.isdir()):
            raise RuntimeError(f"unsupported archive member: {member.name}")
        members.append(member)
    package.extractall(destination, members=members)


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"invalid Agent manifest: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("invalid Agent manifest")
    return value


def _verify_manifest(manifest: dict[str, Any], version: str, channel: str) -> None:
    if manifest.get("kind") != "CapivaraAgentPackage" or manifest.get("platform") != "linux":
        raise RuntimeError("invalid Linux Agent manifest")
    if str(manifest.get("version")) != version:
        raise RuntimeError("package version mismatch")
    manifest_channel = str(manifest.get("channel") or "").lower()
    expected_channel = "beta" if channel == "beta" else "stable"
    if manifest_channel != expected_channel:
        raise RuntimeError("package channel mismatch")


def _verify_package(package_root: Path, version: str, channel: str, external_manifest: dict[str, Any]) -> dict[str, Any]:
    manifest = _load_manifest(package_root / "manifest.json")
    _verify_manifest(manifest, version, channel)
    if manifest != external_manifest:
        raise RuntimeError("external and packaged manifests differ")
    for relative in manifest.get("required_files", []):
        file_path = package_root / str(relative)
        expected = ((manifest.get("files") or {}).get(relative) or {}).get("sha256")
        if not file_path.is_file() or not expected:
            raise RuntimeError(f"invalid package file: {relative}")
        if hashlib.sha256(file_path.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"internal checksum mismatch: {relative}")
    return manifest


def _validate_python(package_root: Path) -> None:
    runtime = package_root / "agent" / "runtime"
    adapters = runtime / "adapters"
    materializers = runtime / "materializers"
    files = [
        runtime / "agent.py", runtime / "capabilities.py", runtime / "network_inventory.py",
        runtime / "update_client.py", runtime / "update_state.py", runtime / "local_cli.py",
        runtime / "cap_dispatch.py", runtime / "game_data_client.py", runtime / "game_data_executor.py",
        runtime / "game_data_state.py", runtime / "instance_runtime.py", runtime / "runtime_spec.py",
        runtime / "runtime_events.py", runtime / "runtime_materialization.py",
        adapters / "__init__.py", adapters / "base.py", adapters / "registry.py", adapters / "systemd.py",
        materializers / "__init__.py", materializers / "base.py", materializers / "registry.py", materializers / "systemd.py",
        package_root / "agent" / "common" / "identity.py", package_root / "agent" / "updater" / "updater.py",
    ]
    completed = subprocess.run(
        ["python3", "-m", "py_compile", *[str(path) for path in files]],
        capture_output=True, text=True, check=False, timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "Python validation failed")[:2000])


def _mapping(package_root: Path) -> list[tuple[Path, Path, int, str]]:
    runtime = package_root / "agent" / "runtime"
    adapters = runtime / "adapters"
    materializers = runtime / "materializers"
    common = package_root / "agent" / "common"
    policy = package_root / "agent" / "policy"
    return [
        (runtime / "agent.py", INSTALL_ROOT / "runtime" / "agent.py", 0o755, "agent/runtime/agent.py"),
        (runtime / "capabilities.py", INSTALL_ROOT / "runtime" / "capabilities.py", 0o644, "agent/runtime/capabilities.py"),
        (runtime / "network_inventory.py", INSTALL_ROOT / "runtime" / "network_inventory.py", 0o644, "agent/runtime/network_inventory.py"),
        (runtime / "update_client.py", INSTALL_ROOT / "runtime" / "update_client.py", 0o644, "agent/runtime/update_client.py"),
        (runtime / "update_state.py", INSTALL_ROOT / "runtime" / "update_state.py", 0o644, "agent/runtime/update_state.py"),
        (runtime / "local_cli.py", INSTALL_ROOT / "runtime" / "local_cli.py", 0o755, "agent/runtime/local_cli.py"),
        (runtime / "cap_dispatch.py", INSTALL_ROOT / "runtime" / "cap_dispatch.py", 0o755, "agent/runtime/cap_dispatch.py"),
        (runtime / "game_data_client.py", INSTALL_ROOT / "runtime" / "game_data_client.py", 0o644, "agent/runtime/game_data_client.py"),
        (runtime / "game_data_executor.py", INSTALL_ROOT / "runtime" / "game_data_executor.py", 0o755, "agent/runtime/game_data_executor.py"),
        (runtime / "game_data_state.py", INSTALL_ROOT / "runtime" / "game_data_state.py", 0o644, "agent/runtime/game_data_state.py"),
        (runtime / "instance_runtime.py", INSTALL_ROOT / "runtime" / "instance_runtime.py", 0o644, "agent/runtime/instance_runtime.py"),
        (runtime / "runtime_spec.py", INSTALL_ROOT / "runtime" / "runtime_spec.py", 0o644, "agent/runtime/runtime_spec.py"),
        (runtime / "runtime_events.py", INSTALL_ROOT / "runtime" / "runtime_events.py", 0o644, "agent/runtime/runtime_events.py"),
        (runtime / "runtime_materialization.py", INSTALL_ROOT / "runtime" / "runtime_materialization.py", 0o644, "agent/runtime/runtime_materialization.py"),
        (adapters / "__init__.py", INSTALL_ROOT / "runtime" / "adapters" / "__init__.py", 0o644, "agent/runtime/adapters/__init__.py"),
        (adapters / "base.py", INSTALL_ROOT / "runtime" / "adapters" / "base.py", 0o644, "agent/runtime/adapters/base.py"),
        (adapters / "registry.py", INSTALL_ROOT / "runtime" / "adapters" / "registry.py", 0o644, "agent/runtime/adapters/registry.py"),
        (adapters / "systemd.py", INSTALL_ROOT / "runtime" / "adapters" / "systemd.py", 0o644, "agent/runtime/adapters/systemd.py"),
        (materializers / "__init__.py", INSTALL_ROOT / "runtime" / "materializers" / "__init__.py", 0o644, "agent/runtime/materializers/__init__.py"),
        (materializers / "base.py", INSTALL_ROOT / "runtime" / "materializers" / "base.py", 0o644, "agent/runtime/materializers/base.py"),
        (materializers / "registry.py", INSTALL_ROOT / "runtime" / "materializers" / "registry.py", 0o644, "agent/runtime/materializers/registry.py"),
        (materializers / "systemd.py", INSTALL_ROOT / "runtime" / "materializers" / "systemd.py", 0o644, "agent/runtime/materializers/systemd.py"),
        (policy / "49-capivara-agent-instance-units.rules", POLKIT_RULES_DIR / "49-capivara-agent-instance-units.rules", 0o644, "agent/policy/49-capivara-agent-instance-units.rules"),
        (common / "identity.py", INSTALL_ROOT / "common" / "identity.py", 0o644, "agent/common/identity.py"),
        (package_root / "agent" / "updater" / "updater.py", INSTALL_ROOT / "updater" / "updater.py", 0o755, "agent/updater/updater.py"),
        (package_root / "manifest.json", INSTALL_ROOT / "manifest.json", 0o644, "manifest.json"),
        (package_root / "VERSION", INSTALL_ROOT / "VERSION", 0o644, "VERSION"),
    ]


def _validate_cli_target() -> tuple[bool, str | None]:
    if not (CLI_PATH.exists() or CLI_PATH.is_symlink()):
        return False, None
    if not CLI_PATH.is_symlink():
        raise RuntimeError(f"{CLI_PATH} exists and is not managed by Capivara Agent")
    target = os.path.realpath(CLI_PATH)
    allowed = {
        os.path.realpath(INSTALL_ROOT / "runtime" / "local_cli.py"),
        os.path.realpath(INSTALL_ROOT / "runtime" / "cap_dispatch.py"),
    }
    if target not in allowed:
        raise RuntimeError(f"{CLI_PATH} points outside the Capivara Agent installation")
    return True, os.readlink(CLI_PATH)


def _reconcile_cli() -> None:
    CLI_PATH.parent.mkdir(parents=True, exist_ok=True)
    expected = INSTALL_ROOT / "runtime" / "cap_dispatch.py"
    temp = CLI_PATH.with_name(f".{CLI_PATH.name}.{os.getpid()}.new")
    try:
        temp.unlink()
    except FileNotFoundError:
        pass
    os.symlink(str(expected), temp)
    os.replace(temp, CLI_PATH)


def _restore_cli(existed: bool, old_target: str | None) -> None:
    try:
        CLI_PATH.unlink()
    except FileNotFoundError:
        pass
    if existed and old_target is not None:
        os.symlink(old_target, CLI_PATH)


def _snapshot_files(mapping: list[tuple[Path, Path, int, str]], backup_root: Path) -> dict[Path, Path | None]:
    snapshots: dict[Path, Path | None] = {}
    for index, (_, destination, _, _) in enumerate(mapping):
        if destination.is_file():
            backup = backup_root / str(index)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(destination, backup)
            snapshots[destination] = backup
        else:
            snapshots[destination] = None
    return snapshots


def _restore_files(snapshots: dict[Path, Path | None]) -> None:
    for destination, backup in reversed(list(snapshots.items())):
        if backup is None:
            try:
                destination.unlink()
            except FileNotFoundError:
                pass
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp = destination.with_name(f".{destination.name}.rollback")
        shutil.copy2(backup, temp)
        os.replace(temp, destination)


def _apply_files(mapping: list[tuple[Path, Path, int, str]]) -> None:
    for source, destination, mode, _ in mapping:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp = destination.with_name(f".{destination.name}.{os.getpid()}.new")
        shutil.copy2(source, temp)
        os.chmod(temp, mode)
        os.replace(temp, destination)


def _validate_installed(version: str, manifest: dict[str, Any], mapping: list[tuple[Path, Path, int, str]]) -> None:
    installed = (INSTALL_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if installed != version:
        raise RuntimeError("post-update VERSION validation failed")
    files = manifest.get("files") or {}
    for _, destination, _, relative in mapping:
        if relative in {"manifest.json", "VERSION"}:
            continue
        expected = ((files.get(relative) or {}).get("sha256"))
        if not expected:
            raise RuntimeError(f"post-update manifest entry missing: {relative}")
        if hashlib.sha256(destination.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"post-update checksum mismatch: {relative}")
    if not CLI_PATH.is_symlink():
        raise RuntimeError("Agent CLI symlink was not reconciled")
    if os.path.realpath(CLI_PATH) != os.path.realpath(INSTALL_ROOT / "runtime" / "cap_dispatch.py"):
        raise RuntimeError("Agent CLI symlink target is invalid")


def _restart_agent() -> None:
    completed = subprocess.run(
        ["systemctl", "restart", "capivara-agent.service"],
        capture_output=True, text=True, check=False, timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "Agent restart failed")[:2000])
    for _ in range(10):
        active = subprocess.run(["systemctl", "is-active", "--quiet", "capivara-agent.service"], check=False, timeout=5)
        if active.returncode == 0:
            return
        time.sleep(0.5)
    raise RuntimeError("Agent service did not become active after update")


def apply_request() -> int:
    if os.geteuid() != 0:
        raise RuntimeError("Linux Agent updater must run as root")
    request = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(request, dict):
        raise RuntimeError("invalid update request")
    version = str(request.get("desired_version", "")).strip()
    channel = str(request.get("channel", "stable")).strip().lower()
    if not version:
        raise RuntimeError("desired_version is required")
    if channel not in {"stable", "beta", "local/manual"}:
        raise RuntimeError("unsupported update channel")
    if channel == "local/manual":
        raise RuntimeError("local/manual updates require administrator supplied package")

    plain_version = version[1:] if version.startswith("v") else version
    tag = version if version.startswith("v") else f"v{version}"
    package_name = f"capivara-agent-linux-{plain_version}"
    archive_name = f"{package_name}.tar.gz"
    manifest_name = f"{package_name}.manifest.json"
    base = f"https://github.com/{REPOSITORY}/releases/download/{tag}"

    with tempfile.TemporaryDirectory(prefix="capivara-agent-update-") as temporary:
        work = Path(temporary)
        archive = work / archive_name
        checksum = work / f"{archive_name}.sha256"
        external_manifest_path = work / manifest_name
        _download(f"{base}/{archive_name}", archive)
        _download(f"{base}/{archive_name}.sha256", checksum)
        _download(f"{base}/{manifest_name}", external_manifest_path)
        expected = checksum.read_text(encoding="utf-8").split()[0].strip().lower()
        if expected != hashlib.sha256(archive.read_bytes()).hexdigest():
            raise RuntimeError("release checksum mismatch")
        external_manifest = _load_manifest(external_manifest_path)
        _verify_manifest(external_manifest, plain_version, channel)
        extract = work / "extract"
        extract.mkdir()
        with tarfile.open(archive, "r:gz") as package:
            _safe_extract(package, extract)
        package_root = extract / package_name
        manifest = _verify_package(package_root, plain_version, channel, external_manifest)
        _validate_python(package_root)

        mapping = _mapping(package_root)
        cli_existed, old_cli_target = _validate_cli_target()
        backup_root = work / "rollback"
        snapshots = _snapshot_files(mapping, backup_root)
        transaction_started = False
        try:
            transaction_started = True
            _apply_files(mapping)
            _reconcile_cli()
            _validate_installed(plain_version, manifest, mapping)
            _restart_agent()
        except Exception:
            if transaction_started:
                _restore_files(snapshots)
                _restore_cli(cli_existed, old_cli_target)
                try:
                    subprocess.run(["systemctl", "restart", "capivara-agent.service"], check=False, timeout=30)
                except (OSError, subprocess.SubprocessError):
                    pass
            raise

    REQUEST_PATH.unlink(missing_ok=True)
    _write_result(
        "applied", installed_version=plain_version, desired_version=plain_version, channel=channel,
        rollout_id=request.get("rollout_id"), batch_number=request.get("batch_number"),
        source=f"github-release:{REPOSITORY}@{tag}",
    )
    return 0


def main() -> int:
    summary = _read_request_summary()
    try:
        return apply_request()
    except Exception as exc:
        REQUEST_PATH.unlink(missing_ok=True)
        _write_result("failed", **summary, error=str(exc)[:2000])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
