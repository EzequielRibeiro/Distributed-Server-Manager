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
SYSTEMD_DIR = Path(os.environ.get("SYSTEMD_DIR", "/etc/systemd/system"))
REQUEST_PATH = STATE_DIR / "update-request.json"
RESULT_PATH = STATE_DIR / "update-result.json"
HISTORY_DIR = STATE_DIR / "update-history"
REPOSITORY = os.environ.get("CAPIVARA_AGENT_GITHUB_REPOSITORY", "EzequielRibeiro/Distributed-Server-Manager")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _ensure_state_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        metadata = STATE_DIR.stat(); os.chown(path, metadata.st_uid, metadata.st_gid); os.chmod(path, 0o700)
    except OSError:
        pass


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    _ensure_state_directory(path.parent)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"); os.chmod(temp, 0o600)
    try:
        metadata = STATE_DIR.stat(); os.chown(temp, metadata.st_uid, metadata.st_gid)
    except OSError:
        pass
    os.replace(temp, path)


def _write_result(status: str, **extra: Any) -> dict[str, Any]:
    payload = {"status": status, "generated_at": _utc_now(), **extra}; _atomic_json(RESULT_PATH, payload)
    _atomic_json(HISTORY_DIR / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json"), payload); return payload


def _read_request_summary() -> dict[str, Any]:
    try: request = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError): return {}
    return {key: request.get(key) for key in ("desired_version", "channel", "rollout_id", "batch_number")} if isinstance(request, dict) else {}


def _download(url: str, path: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "Capivara-Agent-Updater"})
    with urllib.request.urlopen(request, timeout=60) as response, path.open("wb") as output: shutil.copyfileobj(response, output)


def _safe_extract(package: tarfile.TarFile, destination: Path) -> None:
    members = []
    for member in package.getmembers():
        name = PurePosixPath(member.name)
        if name.is_absolute() or ".." in name.parts: raise RuntimeError(f"unsafe archive path: {member.name}")
        if not (member.isfile() or member.isdir()): raise RuntimeError(f"unsupported archive member: {member.name}")
        members.append(member)
    package.extractall(destination, members=members)


def _load_manifest(path: Path) -> dict[str, Any]:
    try: value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc: raise RuntimeError(f"invalid Agent manifest: {exc}") from exc
    if not isinstance(value, dict): raise RuntimeError("invalid Agent manifest")
    return value


def _verify_manifest(manifest: dict[str, Any], version: str, channel: str) -> None:
    if manifest.get("kind") != "CapivaraAgentPackage" or manifest.get("platform") != "linux": raise RuntimeError("invalid Linux Agent manifest")
    if str(manifest.get("version")) != version: raise RuntimeError("package version mismatch")
    expected = "beta" if channel == "beta" else "stable"
    if str(manifest.get("channel") or "").lower() != expected: raise RuntimeError("package channel mismatch")


def _verify_package(package_root: Path, version: str, channel: str, external_manifest: dict[str, Any]) -> dict[str, Any]:
    manifest = _load_manifest(package_root / "manifest.json"); _verify_manifest(manifest, version, channel)
    if manifest != external_manifest: raise RuntimeError("external and packaged manifests differ")
    for relative in manifest.get("required_files", []):
        path = package_root / str(relative); expected = ((manifest.get("files") or {}).get(relative) or {}).get("sha256")
        if not path.is_file() or not expected or hashlib.sha256(path.read_bytes()).hexdigest() != expected: raise RuntimeError(f"invalid package file: {relative}")
    return manifest


def _validate_python(package_root: Path) -> None:
    files = sorted(str(path) for path in (package_root / "agent").rglob("*.py"))
    completed = subprocess.run(["python3", "-m", "py_compile", *files], capture_output=True, text=True, check=False, timeout=60)
    if completed.returncode != 0: raise RuntimeError((completed.stderr or completed.stdout or "Python validation failed")[:2000])


def _mapping(package_root: Path) -> list[tuple[Path, Path, int, str]]:
    mapping: list[tuple[Path, Path, int, str]] = []
    for source in sorted((package_root / "agent" / "runtime").rglob("*.py")):
        rel = source.relative_to(package_root).as_posix(); dest = INSTALL_ROOT / source.relative_to(package_root / "agent")
        mode = 0o755 if source.name in {"agent.py", "local_cli.py", "cap_dispatch.py", "game_data_executor.py", "provisioning_executor.py"} else 0o644
        mapping.append((source, dest, mode, rel))
    fixed = [
        (package_root / "agent/common/identity.py", INSTALL_ROOT / "common/identity.py", 0o644, "agent/common/identity.py"),
        (package_root / "agent/privileged/materialize_instance.py", INSTALL_ROOT / "privileged/materialize_instance.py", 0o755, "agent/privileged/materialize_instance.py"),
        (package_root / "agent/privileged/reconcile_runtime_identity.py", INSTALL_ROOT / "privileged/reconcile_runtime_identity.py", 0o755, "agent/privileged/reconcile_runtime_identity.py"),
        (package_root / "agent/policy/49-capivara-agent-instance-units.rules", POLKIT_RULES_DIR / "49-capivara-agent-instance-units.rules", 0o644, "agent/policy/49-capivara-agent-instance-units.rules"),
        (package_root / "services/capivara-agent-materialize@.service", SYSTEMD_DIR / "capivara-agent-materialize@.service", 0o644, "services/capivara-agent-materialize@.service"),
        (package_root / "services/capivara-agent-runtime-identity.service", SYSTEMD_DIR / "capivara-agent-runtime-identity.service", 0o644, "services/capivara-agent-runtime-identity.service"),
        (package_root / "agent/updater/updater.py", INSTALL_ROOT / "updater/updater.py", 0o755, "agent/updater/updater.py"),
        (package_root / "manifest.json", INSTALL_ROOT / "manifest.json", 0o644, "manifest.json"),
        (package_root / "VERSION", INSTALL_ROOT / "VERSION", 0o644, "VERSION"),
    ]
    return mapping + fixed


def _validate_cli_target() -> tuple[bool, str | None]:
    if not (CLI_PATH.exists() or CLI_PATH.is_symlink()): return False, None
    if not CLI_PATH.is_symlink(): raise RuntimeError(f"{CLI_PATH} exists and is not managed by Capivara Agent")
    target = os.path.realpath(CLI_PATH)
    allowed = {os.path.realpath(INSTALL_ROOT / "runtime/local_cli.py"), os.path.realpath(INSTALL_ROOT / "runtime/cap_dispatch.py")}
    if target not in allowed: raise RuntimeError(f"{CLI_PATH} points outside the Capivara Agent installation")
    return True, os.readlink(CLI_PATH)


def _reconcile_cli() -> None:
    CLI_PATH.parent.mkdir(parents=True, exist_ok=True); expected = INSTALL_ROOT / "runtime/cap_dispatch.py"; temp = CLI_PATH.with_name(f".{CLI_PATH.name}.{os.getpid()}.new")
    try: temp.unlink()
    except FileNotFoundError: pass
    os.symlink(str(expected), temp); os.replace(temp, CLI_PATH)


def _restore_cli(existed: bool, old_target: str | None) -> None:
    try: CLI_PATH.unlink()
    except FileNotFoundError: pass
    if existed and old_target is not None: os.symlink(old_target, CLI_PATH)


def _snapshot_files(mapping: list[tuple[Path, Path, int, str]], backup_root: Path) -> dict[Path, Path | None]:
    snapshots: dict[Path, Path | None] = {}
    for index, (_, destination, _, _) in enumerate(mapping):
        if destination.is_file():
            backup = backup_root / str(index); backup.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(destination, backup); snapshots[destination] = backup
        else: snapshots[destination] = None
    return snapshots


def _restore_files(snapshots: dict[Path, Path | None]) -> None:
    for destination, backup in reversed(list(snapshots.items())):
        if backup is None:
            try: destination.unlink()
            except FileNotFoundError: pass
        else:
            destination.parent.mkdir(parents=True, exist_ok=True); temp = destination.with_name(f".{destination.name}.rollback"); shutil.copy2(backup, temp); os.replace(temp, destination)


def _apply_files(mapping: list[tuple[Path, Path, int, str]]) -> None:
    for source, destination, mode, _ in mapping:
        destination.parent.mkdir(parents=True, exist_ok=True); temp = destination.with_name(f".{destination.name}.{os.getpid()}.new"); shutil.copy2(source, temp); os.chmod(temp, mode); os.replace(temp, destination)


def _daemon_reload() -> None:
    completed = subprocess.run(["systemctl", "daemon-reload"], capture_output=True, text=True, check=False, timeout=30)
    if completed.returncode != 0: raise RuntimeError((completed.stderr or completed.stdout or "systemctl daemon-reload failed")[:2000])


def _reconcile_runtime_identity() -> None:
    completed = subprocess.run(["systemctl", "start", "capivara-agent-runtime-identity.service"], capture_output=True, text=True, check=False, timeout=30)
    if completed.returncode != 0: raise RuntimeError((completed.stderr or completed.stdout or "runtime identity reconciliation failed")[:2000])


def _validate_installed(version: str, manifest: dict[str, Any], mapping: list[tuple[Path, Path, int, str]]) -> None:
    if (INSTALL_ROOT / "VERSION").read_text(encoding="utf-8").strip() != version: raise RuntimeError("post-update VERSION validation failed")
    files = manifest.get("files") or {}
    for _, destination, _, relative in mapping:
        if relative in {"manifest.json", "VERSION"}: continue
        expected = ((files.get(relative) or {}).get("sha256"))
        if not expected or hashlib.sha256(destination.read_bytes()).hexdigest() != expected: raise RuntimeError(f"post-update checksum mismatch: {relative}")
    if not CLI_PATH.is_symlink() or os.path.realpath(CLI_PATH) != os.path.realpath(INSTALL_ROOT / "runtime/cap_dispatch.py"): raise RuntimeError("Agent CLI symlink target is invalid")


def _restart_agent() -> None:
    completed = subprocess.run(["systemctl", "restart", "capivara-agent.service"], capture_output=True, text=True, check=False, timeout=30)
    if completed.returncode != 0: raise RuntimeError((completed.stderr or completed.stdout or "Agent restart failed")[:2000])
    for _ in range(10):
        if subprocess.run(["systemctl", "is-active", "--quiet", "capivara-agent.service"], check=False, timeout=5).returncode == 0: return
        time.sleep(0.5)
    raise RuntimeError("Agent service did not become active after update")


def apply_request() -> int:
    if os.geteuid() != 0: raise RuntimeError("Linux Agent updater must run as root")
    request = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(request, dict): raise RuntimeError("invalid update request")
    version = str(request.get("desired_version", "")).strip(); channel = str(request.get("channel", "stable")).strip().lower()
    if not version: raise RuntimeError("desired_version is required")
    if channel not in {"stable", "beta", "local/manual"}: raise RuntimeError("unsupported update channel")
    if channel == "local/manual": raise RuntimeError("local/manual updates require administrator supplied package")
    plain = version[1:] if version.startswith("v") else version; tag = version if version.startswith("v") else f"v{version}"
    package_name = f"capivara-agent-linux-{plain}"; archive_name = package_name + ".tar.gz"; manifest_name = package_name + ".manifest.json"; base = f"https://github.com/{REPOSITORY}/releases/download/{tag}"
    with tempfile.TemporaryDirectory(prefix="capivara-agent-update-") as temporary:
        work = Path(temporary); archive = work / archive_name; checksum = work / f"{archive_name}.sha256"; external_path = work / manifest_name
        _download(f"{base}/{archive_name}", archive); _download(f"{base}/{archive_name}.sha256", checksum); _download(f"{base}/{manifest_name}", external_path)
        if checksum.read_text().split()[0].strip().lower() != hashlib.sha256(archive.read_bytes()).hexdigest(): raise RuntimeError("release checksum mismatch")
        external = _load_manifest(external_path); _verify_manifest(external, plain, channel); extract = work / "extract"; extract.mkdir()
        with tarfile.open(archive, "r:gz") as package: _safe_extract(package, extract)
        root = extract / package_name; manifest = _verify_package(root, plain, channel, external); _validate_python(root)
        mapping = _mapping(root); cli_existed, old_cli_target = _validate_cli_target(); snapshots = _snapshot_files(mapping, work / "rollback")
        try:
            _apply_files(mapping); _daemon_reload(); _reconcile_runtime_identity(); _reconcile_cli(); _validate_installed(plain, manifest, mapping); _restart_agent()
        except Exception:
            _restore_files(snapshots); _restore_cli(cli_existed, old_cli_target)
            try: _daemon_reload()
            except Exception: pass
            try: subprocess.run(["systemctl", "restart", "capivara-agent.service"], check=False, timeout=30)
            except (OSError, subprocess.SubprocessError): pass
            raise
    REQUEST_PATH.unlink(missing_ok=True)
    _write_result("applied", installed_version=plain, desired_version=plain, channel=channel, rollout_id=request.get("rollout_id"), batch_number=request.get("batch_number"), source=f"github-release:{REPOSITORY}@{tag}")
    return 0


def main() -> int:
    summary = _read_request_summary()
    try: return apply_request()
    except Exception as exc:
        REQUEST_PATH.unlink(missing_ok=True); _write_result("failed", **summary, error=str(exc)[:2000]); return 1


if __name__ == "__main__": raise SystemExit(main())
