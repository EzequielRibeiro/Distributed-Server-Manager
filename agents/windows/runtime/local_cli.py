#!/usr/bin/env python3
"""Local administrative CLI for the Capivara Windows Agent.

This module intentionally exposes only bounded administrative operations. It
never prints credentials or pairing tokens and does not provide arbitrary shell
execution.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

PROGRAM_DATA = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
PROGRAM_FILES = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
DATA_ROOT = Path(os.environ.get("CAPIVARA_AGENT_DATA_ROOT", PROGRAM_DATA / "CapivaraAgent"))
INSTALL_ROOT = Path(os.environ.get("CAPIVARA_AGENT_INSTALL_ROOT", PROGRAM_FILES / "CapivaraAgent"))
CONFIG_PATH = Path(os.environ.get("CAPIVARA_AGENT_CONFIG", DATA_ROOT / "agent.json"))
LOG_PATH = DATA_ROOT / "logs" / "agent.log"
VERSION_PATH = INSTALL_ROOT / "VERSION"
TASK_NAME = os.environ.get("CAPIVARA_AGENT_TASK_NAME", "CapivaraAgent")

_SECRET_KEYS = {
    "credential_secret",
    "pairing_token",
    "token",
    "password",
    "secret",
    "api_key",
}


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, errors="replace")


def _load_config() -> dict[str, Any]:
    value = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise RuntimeError("agent.json must contain a JSON object")
    return value


def _task_state() -> str:
    result = _run("schtasks.exe", "/Query", "/TN", TASK_NAME, "/FO", "LIST", "/V")
    if result.returncode != 0:
        return "missing"
    text = (result.stdout or "").lower()
    for marker in ("running", "em execu", "ready", "pronto", "queued", "fila"):
        if marker in text:
            if marker in {"running", "em execu"}:
                return "running"
            if marker in {"ready", "pronto"}:
                return "ready"
            return "queued"
    return "registered"


def _task(action: str) -> int:
    switches = {"start": "/Run", "stop": "/End"}
    result = _run("schtasks.exe", switches[action], "/TN", TASK_NAME)
    if result.returncode != 0:
        print((result.stderr or result.stdout or "task operation failed").strip(), file=sys.stderr)
    return result.returncode


def _last_heartbeat_line() -> str | None:
    try:
        lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines[-500:]):
        if "heartbeat ok" in line.lower() or "heartbeat failed" in line.lower():
            return line
    return None


def _sanitized(value: Any, key: str = "") -> Any:
    if key.lower() in _SECRET_KEYS or any(part in key.lower() for part in ("secret", "password", "token")):
        return "<redacted>"
    if isinstance(value, dict):
        return {str(k): _sanitized(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitized(item) for item in value]
    return value


def command_status(_: argparse.Namespace) -> int:
    try:
        config = _load_config()
    except Exception as exc:
        config = {}
        config_error = str(exc)
    else:
        config_error = None
    payload = {
        "task": {"name": TASK_NAME, "state": _task_state()},
        "agent_id": config.get("agent_id"),
        "node_id": config.get("node_id"),
        "controller_url": config.get("controller_url"),
        "version": VERSION_PATH.read_text(encoding="utf-8-sig").strip() if VERSION_PATH.exists() else config.get("capivara_version"),
        "last_heartbeat": _last_heartbeat_line(),
    }
    if config_error:
        payload["config_error"] = config_error
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["task"]["state"] != "missing" and not config_error else 1


def command_check(_: argparse.Namespace) -> int:
    checks: list[tuple[str, bool, str]] = []
    checks.append(("config", CONFIG_PATH.is_file(), str(CONFIG_PATH)))
    checks.append(("version", VERSION_PATH.is_file(), str(VERSION_PATH)))
    task_state = _task_state()
    checks.append(("scheduled_task", task_state != "missing", task_state))
    try:
        config = _load_config()
        checks.append(("identity", bool(config.get("agent_id") and config.get("node_id") and config.get("fingerprint")), "present"))
        checks.append(("credential", bool(config.get("credential_id") and config.get("credential_secret")), "present"))
        checks.append(("controller_url", bool(config.get("controller_url")), str(config.get("controller_url") or "missing")))
    except Exception as exc:
        checks.append(("config_json", False, str(exc)))
    heartbeat = _last_heartbeat_line()
    checks.append(("heartbeat_log", bool(heartbeat), heartbeat or "not found"))
    failed = False
    for name, ok, detail in checks:
        print(f"{'OK' if ok else 'FAIL'} {name}: {detail}")
        failed = failed or not ok
    return 1 if failed else 0


def command_doctor(args: argparse.Namespace) -> int:
    code = command_check(args)
    print(f"install_root: {INSTALL_ROOT}")
    print(f"data_root: {DATA_ROOT}")
    print(f"log_path: {LOG_PATH}")
    try:
        config = _load_config()
        print(f"controller: {config.get('controller_url') or 'missing'}")
        print(f"agent_id: {config.get('agent_id') or 'missing'}")
        print(f"node_id: {config.get('node_id') or 'missing'}")
    except Exception:
        pass
    return code


def command_history(args: argparse.Namespace) -> int:
    try:
        lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        print(f"history unavailable: {exc}", file=sys.stderr)
        return 1
    for line in lines[-args.lines :]:
        print(line)
    return 0


def command_version(_: argparse.Namespace) -> int:
    if VERSION_PATH.exists():
        print(VERSION_PATH.read_text(encoding="utf-8-sig").strip())
        return 0
    try:
        print(_load_config().get("capivara_version") or "unknown")
        return 0
    except Exception:
        print("unknown")
        return 1


def command_config(_: argparse.Namespace) -> int:
    try:
        print(json.dumps(_sanitized(_load_config()), indent=2, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"config unavailable: {exc}", file=sys.stderr)
        return 1


def command_start(_: argparse.Namespace) -> int:
    return _task("start")


def command_stop(_: argparse.Namespace) -> int:
    return _task("stop")


def command_restart(_: argparse.Namespace) -> int:
    _task("stop")
    time.sleep(1)
    return _task("start")


def command_relink(args: argparse.Namespace) -> int:
    from relink_cli import relink

    try:
        result = relink(args.token)
    except Exception as exc:
        print(f"RELINK_FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if not args.no_restart:
        return command_restart(args)
    return 0


def _is_admin() -> bool:
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def command_uninstall(args: argparse.Namespace) -> int:
    if not _is_admin():
        print("uninstall requires an elevated Administrator terminal", file=sys.stderr)
        return 1
    try:
        config = _load_config()
    except Exception as exc:
        print(f"cannot verify Agent identity: {exc}", file=sys.stderr)
        return 1
    agent_id = str(config.get("agent_id") or "")
    if not agent_id or args.confirm != agent_id:
        print("refusing uninstall: --confirm must exactly match the Agent ID", file=sys.stderr)
        return 2

    _task("stop")
    _run("schtasks.exe", "/Delete", "/TN", TASK_NAME, "/F")

    cleanup = Path(tempfile.gettempdir()) / f"capivara-uninstall-{os.getpid()}.ps1"
    lines = [
        "Start-Sleep -Seconds 2",
        f"Remove-Item -LiteralPath '{str(INSTALL_ROOT).replace("'", "''")}' -Recurse -Force -ErrorAction SilentlyContinue",
    ]
    if args.purge_data:
        lines.append(f"Remove-Item -LiteralPath '{str(DATA_ROOT).replace("'", "''")}' -Recurse -Force -ErrorAction SilentlyContinue")
    lines.extend(
        [
            "$p=[Environment]::GetEnvironmentVariable('Path','Machine')",
            "$parts=@($p -split ';' | Where-Object { $_ -and $_ -ne '" + str(INSTALL_ROOT / "runtime").replace("'", "''") + "' })",
            "[Environment]::SetEnvironmentVariable('Path',($parts -join ';'),'Machine')",
            "Remove-Item -LiteralPath $MyInvocation.MyCommand.Path -Force -ErrorAction SilentlyContinue",
        ]
    )
    cleanup.write_text("\n".join(lines) + "\n", encoding="utf-8")
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(cleanup)],
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0),
        close_fds=True,
    )
    print("Capivara Agent uninstall scheduled.")
    print("Data root will be purged." if args.purge_data else f"Data preserved at {DATA_ROOT}.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cap", description="Capivara Windows Agent local administration")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, fn in (("status", command_status), ("check", command_check), ("doctor", command_doctor), ("version", command_version), ("config", command_config), ("start", command_start), ("stop", command_stop), ("restart", command_restart)):
        p = sub.add_parser(name)
        p.set_defaults(func=fn)

    p = sub.add_parser("history")
    p.add_argument("--lines", type=int, default=50)
    p.set_defaults(func=command_history)

    p = sub.add_parser("relink")
    p.add_argument("--token", required=True)
    p.add_argument("--no-restart", action="store_true")
    p.set_defaults(func=command_relink)

    p = sub.add_parser("uninstall")
    p.add_argument("--confirm", required=True, help="exact Agent ID")
    p.add_argument("--purge-data", action="store_true")
    p.set_defaults(func=command_uninstall)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
