#!/usr/bin/env python3
"""Small HTTP(S) wrapper for the Dashboard runtime.

Kept outside server.py so transport concerns do not grow the legacy route module.
"""
from __future__ import annotations

import os
import ssl
import threading
from pathlib import Path


def _transport() -> tuple[str, str, int, str | None, str | None]:
    scheme = str(os.environ.get("DSM_WEB_SCHEME", "http") or "http").strip().lower()
    if scheme not in {"http", "https"}:
        raise RuntimeError(f"invalid DSM_WEB_SCHEME: {scheme}")
    # New installer variables are authoritative. Historical runtime overrides remain
    # supported for isolated deployments/tests and existing service environments.
    host = str(
        os.environ.get("DSM_WEB_HOST")
        or os.environ.get("DASHBOARD_HOST")
        or "0.0.0.0"
    ).strip()
    default_port = 8443 if scheme == "https" else 8080
    raw_port = os.environ.get("DSM_WEB_PORT") or os.environ.get("DASHBOARD_PORT") or str(default_port)
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise RuntimeError("DSM_WEB_PORT/DASHBOARD_PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError("Dashboard port must be between 1 and 65535")
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
    context.options |= getattr(ssl, "OP_NO_COMPRESSION", 0)
    context.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    server.socket = context.wrap_socket(server.socket, server_side=True)


def install_transport_security_headers(legacy, *, scheme: str) -> None:
    """Apply transport-aware headers without modifying the legacy route module."""
    handler = legacy.DashboardHandler
    marker = "_capivara_transport_headers_installed"
    if getattr(handler, marker, False):
        return
    previous_send_header = handler.send_header
    previous_end_headers = handler.end_headers

    def send_header(self, keyword, value):
        if scheme == "https" and str(keyword).lower() == "set-cookie":
            cookie = str(value)
            lower = cookie.lower()
            if "secure" not in lower:
                cookie += "; Secure"
            if "samesite=" not in lower:
                cookie += "; SameSite=Lax"
            value = cookie
        return previous_send_header(self, keyword, value)

    def end_headers(self):
        # Security headers belong to the final HTTP transport boundary rather
        # than authentication, static-file delivery, or individual routes.
        previous_send_header(
            self,
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'",
        )
        previous_send_header(self, "X-Content-Type-Options", "nosniff")
        previous_send_header(self, "X-Frame-Options", "DENY")
        previous_send_header(self, "Referrer-Policy", "no-referrer")
        previous_send_header(
            self,
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=()",
        )
        if scheme == "https":
            previous_send_header(
                self,
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return previous_end_headers(self)

    handler.send_header = send_header
    handler.end_headers = end_headers
    setattr(handler, marker, True)


def run_dashboard(legacy) -> None:
    scheme, host, port, cert, key = _transport()
    legacy.validate_environment()
    legacy.HOST = host
    legacy.PORT = port
    install_transport_security_headers(legacy, scheme=scheme)
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


__all__ = ["configure_tls", "install_transport_security_headers", "run_dashboard"]
