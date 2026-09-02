#!/usr/bin/env python3
"""Privileged, typed Capivara Linux Agent self-uninstall executor.

The executor accepts only a request staged by uninstall_client.py. It never
accepts shell commands or browser-provided filesystem paths.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

STATE_DIR = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
REQUEST_PATH = STATE_DIR / "uninstall" / "request.json"
INSTALL_ROOT = Path(os.environ.get("CAPIVARA_AGENT_ROOT", "/opt/capivara-agent"))
CONFIG_DIR = Path(os.environ.get("CAPIVARA_AGENT_CONFIG_DIR", "/etc/capivara-agent"))
SYSTEMD_DIR = Path(os.environ.get("SYSTEMD_DIR", "/etc/systemd/system"))
FINALIZER = Path("/run/capivara-agent-uninstall-finalize.sh")
_ALLOWED_DEFAULT_DATA_ROOTS = {
    Path("/var/lib/capivara-instances"),
    Path("/var/lib/capivara-agent/instances"),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_request() -> dict:
    value = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("kind") != "CapivaraLinuxUninstallRequest":
        raise ValueError("invalid uninstall request")
    if int(value.get("schema_version") or 0) != 1:
        raise ValueError("unsupported uninstall request schema")
    if str(value.get("request_id") or "").startswith("uninstall-") is False:
        raise ValueError("invalid uninstall request_id")
    if value.get("mode") not in {"preserve-data", "purge"}:
        raise ValueError("invalid uninstall mode")
    for key in ("agent_id", "controller_url", "credential_id", "credential_secret", "fingerprint"):
        if not str(value.get(key) or "").strip():
            raise ValueError(f"missing {key}")
    return value


def _headers(request: dict) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Capivara-Agent-Credential": str(request["credential_id"]),
        "X-Capivara-Agent-Secret": str(request["credential_secret"]),
        "X-Capivara-Agent-Fingerprint": str(request["fingerprint"]),
    }


def _report(request: dict, status: str, *, error: str | None = None, host_cleanup: dict | None = None) -> dict:
    stamp_key = {
        "committed": "committed_at",
        "completed": "completed_at",
        "failed": "completed_at",
    }[status]
    uninstall_result = {
        "request_id": request["request_id"],
        "status": status,
        stamp_key: _now(),
    }
    if error:
        uninstall_result["error"] = str(error)[:1000]
    if host_cleanup is not None:
        uninstall_result["host_cleanup"] = host_cleanup
    payload = {
        "agent_id": request["agent_id"],
        "fingerprint": request["fingerprint"],
        "host_identity": request.get("host_identity") or None,
        "uninstall_result": uninstall_result,
        "heartbeat_interval_seconds": 30,
        "degraded_after_seconds": 60,
        "offline_after_seconds": 120,
    }
    url = str(request["controller_url"]).rstrip("/") + "/api/agent/heartbeat"
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(url, data=raw, headers=_headers(request), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            body = response.read().decode("utf-8", errors="replace")
            return json.loads(body or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Controller rejected uninstall result ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Controller unavailable while reporting uninstall: {exc.reason}") from exc


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _stop_runtime() -> None:
    _run("systemctl", "stop", "capivara-agent.service", check=False)
    for unit in (
        "capivara-agent-update.path",
        "capivara-agent-update.service",
        "capivara-agent-runtime-identity.service",
        # Prevent PathExists=request.json from starting a second executor while
        # this oneshot is finishing and before the delayed finalizer removes state.
        "capivara-agent-uninstall.path",
    ):
        _run("systemctl", "stop", unit, check=False)


def _safe_data_root(raw: str) -> Path | None:
    try:
        path = Path(raw).resolve(strict=False)
    except Exception:
        return None
    if path in _ALLOWED_DEFAULT_DATA_ROOTS:
        return path
    return None


def _remove_payload(request: dict) -> dict:
    cleanup = {"service_stopped": False, "runtime_removed": False, "data_removed": False, "mode": request["mode"]}
    _stop_runtime()
    cleanup["service_stopped"] = True

    # Keep only the uninstall executor until the Controller acknowledges completion.
    for child in INSTALL_ROOT.iterdir() if INSTALL_ROOT.exists() else ():
        if child == INSTALL_ROOT / "privileged":
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child, ignore_errors=False)
        else:
            child.unlink(missing_ok=True)
    privileged = INSTALL_ROOT / "privileged"
    if privileged.exists():
        for child in privileged.iterdir():
            if child.name == "uninstall_agent.py":
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child, ignore_errors=False)
            else:
                child.unlink(missing_ok=True)
    cleanup["runtime_removed"] = True

    if request["mode"] == "purge":
        root = _safe_data_root(str(request.get("instance_storage_root") or ""))
        if root and root.exists():
            shutil.rmtree(root)
            cleanup["data_removed"] = True
        elif root:
            cleanup["data_removed"] = True
            cleanup["data_note"] = "managed data root already absent"
        else:
            cleanup["data_note"] = "non-default data root preserved by safety policy"
    return cleanup


def _schedule_finalizer() -> None:
    units = [
        "capivara-agent.service",
        "capivara-agent-update.path",
        "capivara-agent-update.service",
        "capivara-agent-runtime-identity.service",
        "capivara-agent-uninstall.path",
        "capivara-agent-uninstall.service",
    ]
    lines = ["#!/bin/sh", "set -eu"]
    for unit in units:
        lines.append(f"rm -f {SYSTEMD_DIR / unit}")
    lines += [
        f"rm -rf {INSTALL_ROOT}",
        f"rm -rf {CONFIG_DIR}",
        f"rm -rf {STATE_DIR}",
        "systemctl daemon-reload || true",
        "userdel capivara-agent >/dev/null 2>&1 || true",
        f"rm -f {FINALIZER}",
    ]
    FINALIZER.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(FINALIZER, 0o700)
    subprocess.Popen(
        ["systemd-run", "--unit=capivara-agent-uninstall-finalize", "--on-active=2s", "/bin/sh", str(FINALIZER)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def main() -> int:
    if os.geteuid() != 0:
        print("Capivara uninstall executor must run as root", file=sys.stderr)
        return 2
    try:
        request = _load_request()
        _report(request, "committed")
        cleanup = _remove_payload(request)
        _report(request, "completed", host_cleanup=cleanup)
        _schedule_finalizer()
        return 0
    except Exception as exc:
        try:
            request = _load_request()
            _report(request, "failed", error=str(exc), host_cleanup={"mode": request.get("mode")})
        except Exception:
            pass
        print(f"Capivara Agent uninstall failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
