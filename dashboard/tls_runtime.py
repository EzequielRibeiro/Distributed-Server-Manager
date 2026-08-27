#!/usr/bin/env python3
"""Small HTTPS wrapper for the Dashboard runtime.

Kept outside server.py so transport concerns do not grow the legacy route module.
"""
from __future__ import annotations

import os
import ssl
import threading
from pathlib import Path


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _transport() -> tuple[str, str, int, str | None, str | None]:
    scheme = str(os.environ.get("DSM_WEB_SCHEME", "http") or "http").strip().lower()
    if scheme not in {"http", "https"}:
        raise RuntimeError(f"invalid DSM_WEB_SCHEME: {scheme}")
    host = str(os.environ.get("DSM_WEB_HOST", "0.0.0.0") or "0.0.0.0").strip()
    default_port = 8443 if scheme == "https" else 8080
    try:
        port = int(os.environ.get("DSM_WEB_PORT", str(default_port)))
    except ValueError as exc:
        raise RuntimeError("DSM_WEB_PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError("DSM_WEB_PORT must be between 1 and 65535")
    cert = str(os.environ.get("DSM_TLS_CERT_FILE", "") or "").strip() or None
    key = str(os.environ.get("DSM_TLS_KEY_FILE", "") or "").strip() or None
    return scheme, host, port, cert, key


def configure_tls(server, *, scheme: str, cert_file: str | None, key_file: str | None) -> None:
    if scheme != "https":
        return
    if not cert_file or not key_file:
        raise RuntimeError("HTTPS requires DSM_TLS_CERT_FILE and DSM_TLS_KEY_FILE")
    cert_path = Path(cert_file)
    key_path = Path(key_file)
    if not cert_path.is_file():
        raise RuntimeError(f"TLS certificate not found: {cert_path}")
    if not key_path.is_file():
        raise RuntimeError(f"TLS private key not found: {key_path}")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    if hasattr(ssl.TLSVersion, "TLSv1_3"):
        context.maximum_version = ssl.TLSVersion.MAXIMUM_SUPPORTED
    context.options |= getattr(ssl, "OP_NO_COMPRESSION", 0)
    context.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    server.socket = context.wrap_socket(server.socket, server_side=True)


def run_dashboard(legacy) -> None:
    scheme, host, port, cert, key = _transport()
    legacy.validate_environment()
    # Preserve historical globals used by diagnostics/banner while allowing installer config.
    legacy.HOST = host
    legacy.PORT = port
    legacy.print_banner()
    server = legacy.DashboardServer((host, port))
    configure_tls(server, scheme=scheme, cert_file=cert, key_file=key)
    threading.Thread(target=legacy.notification_worker, daemon=True).start()
    public_host = str(os.environ.get("DSM_PUBLIC_HOST", "") or "").strip()
    display_host = public_host or host
    print(f"Acesse | Access: {scheme}://{display_host}:{port}\n")
    if scheme == "https":
        print("TLS: enabled (minimum TLS 1.2)\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando DSM Dashboard... | Shutting down DSM Dashboard...")
    finally:
        server.server_close()


__all__ = ["configure_tls", "run_dashboard"]
