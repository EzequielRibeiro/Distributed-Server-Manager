#!/usr/bin/env python3
"""Manage and diagnose the Controller endpoint used by a Linux Agent."""

from __future__ import annotations

import argparse
import json
import os
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(os.environ.get("CAPIVARA_AGENT_CONFIG", "/etc/capivara-agent/agent.json"))
SERVICE_NAME = os.environ.get("CAPIVARA_AGENT_SERVICE", "capivara-agent.service")


def _read_config() -> dict[str, Any]:
    try:
        payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Agent config not found: {CONFIG_PATH}") from exc
    except PermissionError as exc:
        raise PermissionError(
            "Agent Controller configuration is protected; run this command with sudo."
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Agent config is unreadable: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Agent config must be a JSON object")
    return payload


def _normalize_url(value: str) -> str:
    candidate = value.strip()
    if not candidate:
        raise ValueError("Controller URL cannot be empty")
    parsed = urllib.parse.urlsplit(candidate)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Controller URL must use http:// or https://")
    if not parsed.hostname:
        raise ValueError("Controller URL must include a hostname or IP address")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Controller port must be between 1 and 65535") from exc
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Controller port must be between 1 and 65535")
    if parsed.username or parsed.password:
        raise ValueError("Credentials must not be embedded in the Controller URL")
    if parsed.query or parsed.fragment:
        raise ValueError("Controller URL must not contain query parameters or fragments")
    path = parsed.path.rstrip("/")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _write_config(config: dict[str, Any]) -> None:
    try:
        original = CONFIG_PATH.stat()
    except OSError as exc:
        raise RuntimeError(f"Unable to inspect Agent config: {exc}") from exc
    temp = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".tmp")
    try:
        temp.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(temp, 0o600)
        if hasattr(os, "chown"):
            os.chown(temp, original.st_uid, original.st_gid)
        temp.replace(CONFIG_PATH)
        os.chmod(CONFIG_PATH, 0o600)
    except PermissionError as exc:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise PermissionError(
            "Agent Controller configuration is protected; run this command with sudo."
        ) from exc
    except OSError as exc:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise RuntimeError(f"Unable to update Agent config: {exc}") from exc


def _restart_service() -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["systemctl", "restart", SERVICE_NAME],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"attempted": True, "ok": False, "error": str(exc)}
    detail = (completed.stderr or completed.stdout or "").strip()
    return {
        "attempted": True,
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "detail": detail or None,
    }


def _endpoint_parts(url: str) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(url)
    default_port = 443 if parsed.scheme == "https" else 80
    return {
        "url": url,
        "scheme": parsed.scheme,
        "host": parsed.hostname,
        "port": parsed.port or default_port,
        "path": parsed.path or "",
    }


def _probe(url: str, config: dict[str, Any] | None = None, timeout: float = 5.0) -> dict[str, Any]:
    normalized = _normalize_url(url)
    endpoint = _endpoint_parts(normalized)
    host = str(endpoint["host"])
    port = int(endpoint["port"])
    result: dict[str, Any] = {
        "controller_url": normalized,
        "endpoint": endpoint,
        "dns": {"ok": False},
        "tcp": {"ok": False},
        "tls": {"required": endpoint["scheme"] == "https", "ok": endpoint["scheme"] != "https"},
        "http": {"ok": False},
        "authentication": {
            "configured": bool(config and config.get("credential_id") and config.get("credential_secret")),
            "verified": False,
            "note": "Permanent Agent credential is configured locally; /ping does not require authentication."
            if config and config.get("credential_id") and config.get("credential_secret")
            else "Agent is not enrolled with a permanent credential yet.",
        },
        "ok": False,
    }

    started = time.monotonic()
    try:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        addresses = sorted({record[4][0] for record in records})
        result["dns"] = {"ok": True, "addresses": addresses}
    except OSError as exc:
        result["dns"] = {"ok": False, "error": str(exc)}
        result["elapsed_ms"] = round((time.monotonic() - started) * 1000, 1)
        return result

    tcp_started = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
        result["tcp"] = {
            "ok": True,
            "latency_ms": round((time.monotonic() - tcp_started) * 1000, 1),
        }
    except OSError as exc:
        result["tcp"] = {"ok": False, "error": str(exc)}
        result["elapsed_ms"] = round((time.monotonic() - started) * 1000, 1)
        return result

    if endpoint["scheme"] == "https":
        tls_started = time.monotonic()
        try:
            context = ssl.create_default_context()
            with socket.create_connection((host, port), timeout=timeout) as raw:
                with context.wrap_socket(raw, server_hostname=host) as secured:
                    certificate = secured.getpeercert()
                    result["tls"] = {
                        "required": True,
                        "ok": True,
                        "latency_ms": round((time.monotonic() - tls_started) * 1000, 1),
                        "protocol": secured.version(),
                        "cipher": secured.cipher()[0] if secured.cipher() else None,
                        "subject": certificate.get("subject"),
                        "not_after": certificate.get("notAfter"),
                    }
        except (OSError, ssl.SSLError) as exc:
            result["tls"] = {"required": True, "ok": False, "error": str(exc)}
            result["elapsed_ms"] = round((time.monotonic() - started) * 1000, 1)
            return result

    ping_url = normalized.rstrip("/") + "/ping"
    request = urllib.request.Request(
        ping_url,
        headers={"Accept": "application/json", "User-Agent": "Capivara-Agent-Controller-Test"},
        method="GET",
    )
    http_started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            status = int(response.status)
            result["http"] = {
                "ok": 200 <= status < 300,
                "status_code": status,
                "latency_ms": round((time.monotonic() - http_started) * 1000, 1),
                "response": body[:500],
            }
    except urllib.error.HTTPError as exc:
        result["http"] = {
            "ok": False,
            "status_code": exc.code,
            "error": str(exc),
        }
    except (urllib.error.URLError, OSError) as exc:
        result["http"] = {"ok": False, "error": str(exc)}

    result["ok"] = bool(
        result["dns"].get("ok")
        and result["tcp"].get("ok")
        and result["tls"].get("ok")
        and result["http"].get("ok")
    )
    result["elapsed_ms"] = round((time.monotonic() - started) * 1000, 1)
    return result


def _show(config: dict[str, Any]) -> dict[str, Any]:
    raw = str(config.get("controller_url") or "").strip()
    if not raw:
        return {"configured": False, "controller_url": None}
    normalized = _normalize_url(raw)
    return {
        "configured": True,
        **_endpoint_parts(normalized),
        "agent_id": config.get("agent_id"),
        "controller_id": config.get("controller_id"),
        "enrolled": bool(config.get("credential_id") and config.get("credential_secret")),
    }


def _emit(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        return
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            print(f"{key}: {json.dumps(value, ensure_ascii=False, default=str)}")
        else:
            print(f"{key}: {value}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cap agent controller")
    sub = parser.add_subparsers(dest="action", required=True)

    show = sub.add_parser("show", help="Show the configured Controller endpoint")
    show.add_argument("--json", action="store_true", dest="as_json")

    set_parser = sub.add_parser("set", help="Set the Controller endpoint and restart the Agent")
    set_parser.add_argument("url")
    set_parser.add_argument("--no-restart", action="store_true")
    set_parser.add_argument("--json", action="store_true", dest="as_json")

    test = sub.add_parser("test", help="Test DNS, TCP, TLS and Controller /ping reachability")
    test.add_argument("url", nargs="?", help="Optional endpoint to test without saving it")
    test.add_argument("--timeout", type=float, default=5.0)
    test.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    try:
        config = _read_config()
        if args.action == "show":
            payload = _show(config)
        elif args.action == "set":
            url = _normalize_url(args.url)
            previous = str(config.get("controller_url") or "").strip() or None
            config["controller_url"] = url
            _write_config(config)
            restart = {"attempted": False, "ok": True}
            if not args.no_restart:
                restart = _restart_service()
            payload = {
                "updated": True,
                "previous_controller_url": previous,
                "controller_url": url,
                "service_restart": restart,
            }
            if not restart.get("ok", False):
                _emit(payload, bool(args.as_json))
                return 1
        else:
            target = args.url or str(config.get("controller_url") or "").strip()
            if not target:
                raise ValueError("Controller URL is not configured; provide a URL to test")
            if args.timeout <= 0 or args.timeout > 60:
                raise ValueError("--timeout must be greater than 0 and at most 60 seconds")
            payload = _probe(target, config=config, timeout=float(args.timeout))
            _emit(payload, bool(args.as_json))
            return 0 if payload.get("ok") else 1
        _emit(payload, bool(args.as_json))
        return 0
    except PermissionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
