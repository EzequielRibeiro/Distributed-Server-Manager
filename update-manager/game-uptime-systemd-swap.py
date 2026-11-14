#!/usr/bin/env python3
"""DSM #928: reversible unit-file swap for *disposable* systemd units only.

This is deliberately separate from the Capivara systemd materializer and from
update.sh. Production unit names and paths are refused. No service start,
restart, stop, game management, or live no-drain authorization occurs here.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from typing import Callable, Mapping

_UNIT = re.compile(r"dsm928-e2e-[a-z0-9-]+\.service\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_REAL_UNITS = Path("/run/systemd/system")
_MARKER = "# DSM928_DISPOSABLE_UNIT_V1"
_MAX = 8192


class DisposableSwapError(RuntimeError):
    pass


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _workspace(path: Path) -> Path:
    path = Path(path)
    if path.is_symlink() or not path.is_dir():
        raise DisposableSwapError("unsafe disposable journal directory")
    resolved = path.resolve(strict=True)
    temporary = Path(tempfile.gettempdir()).resolve(strict=True)
    if resolved == temporary or temporary not in resolved.parents:
        raise DisposableSwapError("journal must remain inside a /tmp fixture")
    if resolved.stat().st_mode & 0o077:
        raise DisposableSwapError("transaction journal directory is not private")
    return resolved


def _host_safe_for_disposable_systemd() -> bool:
    if os.environ.get("CAPIVARA_DSM928_SYSTEMD_E2E") != "1" or os.geteuid() != 0:
        return False
    if Path("/opt/dsm").exists() or Path("/opt/capivara-agent").exists():
        return False
    if not _REAL_UNITS.is_dir() or _REAL_UNITS.is_symlink():
        return False
    try:
        result = subprocess.run(
            ["systemctl", "list-units", "--all", "--type=service",
             "--state=active", "--no-legend", "--plain",
             "capivara-instance-*.service"],
            check=False, capture_output=True, text=True, timeout=8,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and not result.stdout.strip()


def _unit_path(workspace: Path, name: str, *, unit_dir: Path, runner) -> Path:
    if not isinstance(name, str) or not _UNIT.fullmatch(name):
        raise DisposableSwapError("only dsm928-e2e units are permitted")
    root = Path(unit_dir)
    if root.is_symlink() or not root.is_dir() or not root.is_absolute():
        raise DisposableSwapError("unsafe unit-file directory")
    resolved = root.resolve(strict=True)
    if resolved == _REAL_UNITS:
        if not _host_safe_for_disposable_systemd() or runner is not None:
            raise DisposableSwapError("real systemd requires an isolated CI runner")
    elif workspace != resolved and workspace not in resolved.parents:
        raise DisposableSwapError("test unit directory must be inside /tmp workspace")
    elif runner is None:
        raise DisposableSwapError("fixture-only unit directory requires a fake runner")
    return resolved / name


def _fixture_bytes(content: bytes, name: str) -> None:
    if not isinstance(content, bytes) or not (80 <= len(content) <= _MAX):
        raise DisposableSwapError("unit fixture is absent or oversized")
    try:
        lines = content.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise DisposableSwapError("invalid unit fixture encoding") from exc
    if (len(lines) < 6 or lines[0] != _MARKER
            or lines[1] != "# DSM928_UNIT=" + name):
        raise DisposableSwapError("unit is not marked as the exact disposable fixture")
    commands = [line[10:] for line in lines if line.startswith("ExecStart=")]
    # The fixture may only run a benign, bounded sleep; this is intentionally
    # NOT a production Minecraft unit renderer or generic systemd executor.
    if len(commands) != 1 or not re.fullmatch(r"/usr/bin/sleep (?:1[2-9][0-9]|2[0-4][0-9])", commands[0]):
        raise DisposableSwapError("disposable unit ExecStart is not allowlisted")
    if (lines.count("[Service]") != 1 or lines.count("[Unit]") != 1
            or any(line.startswith(("ExecStartPre=", "ExecStop=", "ExecReload=",
                                    "ExecStopPost=", "OnFailure=", "Requires=",
                                    "Wants=", "EnvironmentFile=", "User=",
                                    "Group=", "KillSignal=", "Restart="))
                   for line in lines)):
        raise DisposableSwapError("unsupported commands or service directives")


def _read_unit(path: Path, name: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise DisposableSwapError("existing unit missing or symlinked")
    st = path.stat()
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > _MAX:
        raise DisposableSwapError("unsafe existing unit file")
    data = path.read_bytes()
    _fixture_bytes(data, name)
    return data


def _snapshot(name: str, inspect: Callable[[str], Mapping]) -> dict:
    try:
        row = inspect(name)
        if (not isinstance(row, Mapping) or row.get("unit") != name
                or row.get("state") != "active"
                or type(row.get("pid")) is not int or row["pid"] < 2
                or type(row.get("started")) is not int or row["started"] < 1):
            raise ValueError("invalid active unit identity")
        return {"unit": name, "state": "active", "pid": row["pid"],
                "started": row["started"]}
    except Exception as exc:
        raise DisposableSwapError("cannot establish active disposable process") from exc


def _fsync_dir(directory: Path):
    fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_write(path: Path, content: bytes, *, exclusive: bool = False):
    if path.is_symlink():
        raise DisposableSwapError("refuse symlink target")
    if exclusive and (path.exists() or path.is_symlink()):
        raise DisposableSwapError("transaction artifact already exists")
    temporary = path.with_name("." + path.name + ".dsm928.part")
    if temporary.exists() or temporary.is_symlink():
        raise DisposableSwapError("stale transaction staging file")
    flags = os.O_CREAT | os.O_WRONLY | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600 if path.name.endswith((".json", ".backup")) else 0o644)
        if exclusive and path.exists():
            raise DisposableSwapError("transaction artifact appeared during write")
        os.replace(temporary, path)
        _fsync_dir(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _journal(workspace: Path, values: dict) -> None:
    file = workspace / "dsm928-unit-swap.json"
    _atomic_write(file, (json.dumps(values, sort_keys=True) + "\n").encode("utf-8"))


def _load_journal(workspace: Path) -> dict:
    file = workspace / "dsm928-unit-swap.json"
    if file.is_symlink() or not file.is_file() or file.stat().st_size > _MAX:
        raise DisposableSwapError("missing or unsafe unit swap journal")
    try:
        record = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise DisposableSwapError("unreadable unit swap journal") from exc
    if (not isinstance(record, dict)
            or record.get("kind") != "DSM928DisposableSystemdSwap"
            or record.get("scope") != "disposable_only_not_production"
            or record.get("live_no_drain_authorized") is not False):
        raise DisposableSwapError("invalid unit swap journal identity")
    return record


def _reload(runner) -> None:
    if runner is None:
        try:
            result = subprocess.run(["systemctl", "daemon-reload"],
                                    check=False, capture_output=True,
                                    text=True, timeout=20)
            good = result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            good = False
    else:
        good = runner() is True
    if not good:
        raise DisposableSwapError("disposable systemd daemon-reload failed")


def swap_unit(workspace: Path, name: str, *, unit_dir: Path,
              candidate: bytes, expected_old_sha256: str,
              inspect: Callable[[str], Mapping], runner=None) -> dict:
    """One fail-closed disposable unit-file swap; rollback on caught errors."""
    root = _workspace(workspace)
    path = _unit_path(root, name, unit_dir=unit_dir, runner=runner)
    if (not isinstance(expected_old_sha256, str)
            or not _SHA.fullmatch(expected_old_sha256)):
        raise DisposableSwapError("old unit SHA-256 baseline is required")
    journal_file = root / "dsm928-unit-swap.json"
    backup_file = root / "dsm928-unit-old.backup"
    if (journal_file.exists() or journal_file.is_symlink()
            or backup_file.exists() or backup_file.is_symlink()):
        raise DisposableSwapError("existing unit transaction requires manual review")
    old = _read_unit(path, name)
    _fixture_bytes(candidate, name)
    if _sha(old) != expected_old_sha256 or old == candidate:
        raise DisposableSwapError("stale unit baseline or identical candidate")
    before = _snapshot(name, inspect)
    # Persist the old bytes and intent BEFORE any actual unit replacement.
    _atomic_write(backup_file, old, exclusive=True)
    record = {
        "kind": "DSM928DisposableSystemdSwap",
        "scope": "disposable_only_not_production",
        "status": "prepared",
        "unit": name, "old_sha256": _sha(old),
        "new_sha256": _sha(candidate), "original_identity": before,
        "live_no_drain_authorized": False,
    }
    _journal(root, record)
    try:
        if _read_unit(path, name) != old or _snapshot(name, inspect) != before:
            raise DisposableSwapError("concurrent unit or process change")
        _atomic_write(path, candidate)
        _reload(runner)
        if _read_unit(path, name) != candidate or _snapshot(name, inspect) != before:
            raise DisposableSwapError("unit swap changed running process or file")
        record["status"] = "applied"
        _journal(root, record)
        return {"status": "applied", "unit": name,
                "original_identity": before, "live_no_drain_authorized": False}
    except Exception as exc:
        try:
            current = _read_unit(path, name)
            if current not in (old, candidate) or _snapshot(name, inspect) != before:
                raise DisposableSwapError("cannot safely compensate unexpected unit or process")
            record["status"] = "rollback_started"
            _journal(root, record)
            _atomic_write(path, old)
            _reload(runner)
            if _read_unit(path, name) != old or _snapshot(name, inspect) != before:
                raise DisposableSwapError("rollback verification failed")
            record["status"] = "rolled_back"
            _journal(root, record)
        except Exception as rollback_exc:
            record["status"] = "manual_recovery_required"
            _journal(root, record)
            raise DisposableSwapError("unit rollback failed; manual review required") from rollback_exc
        raise DisposableSwapError("unit swap failed and rollback completed") from exc


def restore_unit(workspace: Path, name: str, *, unit_dir: Path,
                 inspect: Callable[[str], Mapping],
                 operator_reviewed: bool = False, runner=None) -> dict:
    """Manually reviewed restore, no replay after terminal or interrupted rollback."""
    root = _workspace(workspace)
    path = _unit_path(root, name, unit_dir=unit_dir, runner=runner)
    if operator_reviewed is not True:
        raise DisposableSwapError("explicit operator review required")
    record = _load_journal(root)
    if record.get("unit") != name or record.get("status") not in {"applied", "prepared"}:
        raise DisposableSwapError("not a recoverable unit swap journal")
    backup = root / "dsm928-unit-old.backup"
    if backup.is_symlink() or not backup.is_file() or backup.stat().st_size > _MAX:
        raise DisposableSwapError("missing or unsafe unit backup")
    old = backup.read_bytes()
    _fixture_bytes(old, name)
    if _sha(old) != record.get("old_sha256"):
        raise DisposableSwapError("backup digest mismatch")
    current = _read_unit(path, name)
    if _sha(current) not in {record.get("old_sha256"), record.get("new_sha256")}:
        raise DisposableSwapError("unit changed since swap; refuse recovery")
    if _snapshot(name, inspect) != record.get("original_identity"):
        raise DisposableSwapError("process changed since swap; manual recovery required")
    record["status"] = "recovery_started"
    _journal(root, record)
    try:
        _atomic_write(path, old)
        _reload(runner)
        if _read_unit(path, name) != old or _snapshot(name, inspect) != record["original_identity"]:
            raise DisposableSwapError("unit or process changed during recovery")
        record["status"] = "restored"
        _journal(root, record)
        return {"status": "restored", "unit": name,
                "live_no_drain_authorized": False}
    except Exception as exc:
        record["status"] = "manual_recovery_required"
        _journal(root, record)
        raise DisposableSwapError("unit recovery failed; manual review required") from exc
