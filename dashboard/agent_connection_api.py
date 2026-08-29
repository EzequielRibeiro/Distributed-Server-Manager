#!/usr/bin/env python3
"""Non-destructive remote Agent connectivity checks for the Dashboard."""
from __future__ import annotations

import os
import stat
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from core.agent_ssh_deploy import AgentDeployError, SSHDeployOptions, preflight_ssh, preflight_windows_ssh

MAX_DASHBOARD_BATCH = 500
MAX_DASHBOARD_CONCURRENCY = 20


def _authorized(user: dict[str, Any] | None) -> None:
    role = str((user or {}).get("role", "")).strip().lower()
    if role not in {"admin", "controller"}:
        raise PermissionError("Agent connection test is not permitted")


def _authorized_file(raw: Any, *, env_name: str, default_root: str, label: str, require_private_mode: bool = False) -> str | None:
    value = str(raw or "").strip()
    if not value:
        return None
    root = Path(os.environ.get(env_name, default_root)).resolve()
    path = Path(value).expanduser().resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} must be inside {root}") from exc
    if not path.is_file():
        raise ValueError(f"{label} was not found: {path}")
    if require_private_mode:
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            raise ValueError(f"{label} has unsafe permissions {mode:04o}; use 0600 or more restrictive")
    return str(path)


def _password_file(raw: Any) -> str | None:
    return _authorized_file(
        raw,
        env_name="DSM_REMOTE_DEPLOY_SECRET_DIR",
        default_root="/etc/capivara/secrets/remote-deploy",
        label="password_file",
        require_private_mode=True,
    )


def _identity_file(raw: Any) -> str | None:
    return _authorized_file(
        raw,
        env_name="DSM_REMOTE_DEPLOY_IDENTITY_DIR",
        default_root="/etc/capivara/ssh/remote-deploy",
        label="identity_file",
        require_private_mode=True,
    )


def _options(payload: dict[str, Any]) -> tuple[str, SSHDeployOptions]:
    if payload.get("password") not in (None, "") or payload.get("ssh_password") not in (None, ""):
        raise ValueError("SSH passwords are never accepted directly; use password_file")
    platform = str(payload.get("platform", "linux")).strip().lower()
    if platform not in {"linux", "windows"}:
        raise ValueError("unsupported Agent platform")
    host = str(payload.get("ssh_host", payload.get("host", "")) or "").strip()
    ssh_user = str(payload.get("ssh_user", payload.get("user", "")) or "").strip()
    if not host:
        raise ValueError("ssh_host is required")
    if not ssh_user:
        raise ValueError("ssh_user is required")
    try:
        port = int(payload.get("ssh_port", payload.get("port", 22)) or 22)
    except (TypeError, ValueError) as exc:
        raise ValueError("ssh_port must be an integer") from exc
    password_file = _password_file(payload.get("password_file"))
    identity_file = _identity_file(payload.get("identity_file"))
    if password_file and identity_file:
        raise ValueError("use either password_file or identity_file, not both")
    return platform, SSHDeployOptions(
        host=host,
        ssh_user=ssh_user,
        ssh_port=port,
        password_file=password_file,
        identity_file=identity_file,
    )


def _test_one(payload: dict[str, Any], *, ssh_runner=None) -> dict[str, Any]:
    platform, options = _options(payload)
    try:
        fn = preflight_windows_ssh if platform == "windows" else preflight_ssh
        result = fn(options) if ssh_runner is None else fn(options, runner=ssh_runner)
    except AgentDeployError as exc:
        raise ValueError(str(exc)) from exc
    return {
        "ok": True,
        "host": options.host,
        "ssh_user": options.ssh_user,
        "ssh_port": options.ssh_port,
        "platform": result.get("platform", platform),
        "architecture": result.get("architecture"),
        "transport": "openssh",
        "authentication": "password-file" if options.password_file else ("identity-file" if options.identity_file else "ssh-agent/default-key"),
    }


def test_agent_connection_for_user(user: dict[str, Any] | None, payload: dict[str, Any] | None, *, ssh_runner=None) -> dict[str, Any]:
    _authorized(user)
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    return _test_one(payload, ssh_runner=ssh_runner)


def test_agent_connections_for_user(user: dict[str, Any] | None, payload: dict[str, Any] | None, *, ssh_runner=None) -> dict[str, Any]:
    _authorized(user)
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    targets = payload.get("targets")
    if not isinstance(targets, list) or not targets:
        raise ValueError("targets must be a non-empty array")
    if len(targets) > MAX_DASHBOARD_BATCH:
        raise ValueError(f"batch exceeds maximum of {MAX_DASHBOARD_BATCH} targets")
    try:
        concurrency = int(payload.get("concurrency", 5) or 5)
    except (TypeError, ValueError) as exc:
        raise ValueError("concurrency must be an integer") from exc
    if not 1 <= concurrency <= MAX_DASHBOARD_CONCURRENCY:
        raise ValueError(f"concurrency must be between 1 and {MAX_DASHBOARD_CONCURRENCY}")

    common = {k: v for k, v in payload.items() if k != "targets"}
    results: list[dict[str, Any] | None] = [None] * len(targets)

    def run(index: int, target: Any):
        if not isinstance(target, dict):
            return index, {"ok": False, "status": "invalid", "error": "target must be an object"}
        merged = dict(common)
        merged.update(target)
        label = str(target.get("name", "") or "").strip() or None
        try:
            result = _test_one(merged, ssh_runner=ssh_runner)
            result.update(name=label, status="reachable")
            return index, result
        except (ValueError, OSError) as exc:
            return index, {
                "ok": False,
                "name": label,
                "host": str(merged.get("ssh_host", merged.get("host", "")) or ""),
                "status": "failed",
                "error": str(exc),
            }

    workers = min(concurrency, len(targets))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="dashboard-ssh-test") as executor:
        futures = [executor.submit(run, index, target) for index, target in enumerate(targets)]
        for future in as_completed(futures):
            index, result = future.result()
            results[index] = result
    succeeded = sum(1 for result in results if result and result.get("ok"))
    return {
        "ok": succeeded == len(results),
        "total": len(results),
        "succeeded": succeeded,
        "failed": len(results) - succeeded,
        "targets": results,
    }
