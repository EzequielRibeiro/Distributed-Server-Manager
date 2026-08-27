#!/usr/bin/env python3
from __future__ import annotations

import os
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
if str(DASHBOARD) not in sys.path:
    sys.path.insert(0, str(DASHBOARD))

from tls_runtime import _transport, configure_tls


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        body = b"capivara-tls-ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ControllerTlsTransportTest(unittest.TestCase):
    def setUp(self):
        self.saved = {key: os.environ.get(key) for key in (
            "DSM_WEB_SCHEME", "DSM_WEB_HOST", "DSM_WEB_PORT",
            "DSM_TLS_CERT_FILE", "DSM_TLS_KEY_FILE",
        )}

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_http_is_supported_as_explicit_local_default(self):
        for key in self.saved:
            os.environ.pop(key, None)
        scheme, host, port, cert, key = _transport()
        self.assertEqual(scheme, "http")
        self.assertEqual(host, "0.0.0.0")
        self.assertEqual(port, 8080)
        self.assertIsNone(cert)
        self.assertIsNone(key)

    def test_https_requires_certificate_and_key(self):
        os.environ["DSM_WEB_SCHEME"] = "https"
        os.environ["DSM_WEB_PORT"] = "8443"
        os.environ.pop("DSM_TLS_CERT_FILE", None)
        os.environ.pop("DSM_TLS_KEY_FILE", None)
        scheme, _, _, cert, key = _transport()
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        try:
            with self.assertRaises(RuntimeError):
                configure_tls(server, scheme=scheme, cert_file=cert, key_file=key)
        finally:
            server.server_close()

    @unittest.skipUnless(subprocess.run(["sh", "-c", "command -v openssl >/dev/null"], capture_output=True).returncode == 0, "openssl unavailable")
    def test_https_serves_with_hostname_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cert = root / "server.crt"
            key = root / "server.key"
            subprocess.run([
                "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256",
                "-days", "1", "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost",
                "-keyout", str(key), "-out", str(cert),
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            configure_tls(server, scheme="https", cert_file=str(cert), key_file=str(key))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                context = ssl.create_default_context(cafile=str(cert))
                with socket.create_connection(("127.0.0.1", server.server_address[1]), timeout=5) as raw:
                    with context.wrap_socket(raw, server_hostname="localhost") as secure:
                        self.assertGreaterEqual(secure.version(), "TLSv1.2")
                        secure.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
                        response = b""
                        while True:
                            chunk = secure.recv(4096)
                            if not chunk:
                                break
                            response += chunk
                self.assertIn(b"200 OK", response)
                self.assertIn(b"capivara-tls-ok", response)
            finally:
                server.shutdown()
                server.server_close()

    def test_installer_supports_http_and_three_https_certificate_modes(self):
        helper = (ROOT / "installer" / "web_transport.sh").read_text(encoding="utf-8")
        installer = (ROOT / "install.sh").read_text(encoding="utf-8")
        config = (ROOT / "config" / "dsm.conf").read_text(encoding="utf-8")
        runtime = (ROOT / "dashboard" / "tls_runtime.py").read_text(encoding="utf-8")
        for token in ("DSM_WEB_SCHEME", "letsencrypt", "existing", "selfsigned", "DSM_TLS_CERT_FILE", "DSM_TLS_KEY_FILE", "DSM_TLS_CA_FILE"):
            self.assertIn(token, helper)
        self.assertIn("select_web_transport", installer)
        self.assertIn("persist_web_transport_config", installer)
        self.assertIn('DSM_WEB_SCHEME="http"', config)
        self.assertIn("Strict-Transport-Security", runtime)
        self.assertIn("; Secure", runtime)
        self.assertIn("SameSite=Lax", runtime)
        self.assertIn("renewal-hooks/deploy/capivara-dashboard", helper)

    def test_noninteractive_http_and_https_selection_contract(self):
        helper = ROOT / "installer" / "web_transport.sh"
        http = subprocess.run([
            "bash", "-c",
            f'source "{helper}"; DSM_NODE_ROLE=controller DSM_NON_INTERACTIVE=1 DSM_WEB_SCHEME=http select_web_transport; printf "%s|%s" "$DSM_WEB_SCHEME" "$DSM_WEB_PORT"',
        ], check=True, text=True, capture_output=True)
        self.assertEqual(http.stdout, "http|8080")
        https = subprocess.run([
            "bash", "-c",
            f'source "{helper}"; DSM_NODE_ROLE=controller DSM_NON_INTERACTIVE=1 DSM_WEB_SCHEME=https DSM_TLS_CERT_MODE=existing DSM_TLS_CERT_FILE=/tmp/a.crt DSM_TLS_KEY_FILE=/tmp/a.key select_web_transport; printf "%s|%s|%s" "$DSM_WEB_SCHEME" "$DSM_WEB_PORT" "$DSM_TLS_CERT_MODE"',
        ], check=True, text=True, capture_output=True)
        self.assertEqual(https.stdout, "https|8443|existing")


if __name__ == "__main__":
    unittest.main()
