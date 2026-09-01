#!/usr/bin/env python3
from __future__ import annotations

import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
if str(DASHBOARD) not in sys.path:
    sys.path.insert(0, str(DASHBOARD))

from tls_runtime import configure_tls


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        body = b"capivara-tls-resilient"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@unittest.skipUnless(
    subprocess.run(
        ["sh", "-c", "command -v openssl >/dev/null"],
        capture_output=True,
    ).returncode == 0,
    "openssl unavailable",
)
class ControllerTlsAcceptResilienceTest(unittest.TestCase):
    def test_stalled_tls_peer_does_not_block_valid_https_client(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cert = root / "server.crt"
            key = root / "server.key"
            subprocess.run(
                [
                    "openssl", "req", "-x509", "-newkey", "rsa:2048",
                    "-nodes", "-sha256", "-days", "1", "-subj", "/CN=localhost",
                    "-addext", "subjectAltName=DNS:localhost",
                    "-keyout", str(key), "-out", str(cert),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            configure_tls(
                server,
                scheme="https",
                cert_file=str(cert),
                key_file=str(key),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            stalled = socket.create_connection(
                ("127.0.0.1", server.server_address[1]),
                timeout=2,
            )
            try:
                # Give the server enough time to accept the raw TCP peer. The
                # client deliberately sends no TLS ClientHello.
                time.sleep(0.2)
                context = ssl.create_default_context(cafile=str(cert))
                with socket.create_connection(
                    ("127.0.0.1", server.server_address[1]),
                    timeout=2,
                ) as raw:
                    with context.wrap_socket(raw, server_hostname="localhost") as secure:
                        secure.settimeout(2)
                        secure.sendall(
                            b"GET / HTTP/1.1\r\n"
                            b"Host: localhost\r\n"
                            b"Connection: close\r\n\r\n"
                        )
                        response = b""
                        while True:
                            chunk = secure.recv(4096)
                            if not chunk:
                                break
                            response += chunk
                self.assertIn(b"200 OK", response)
                self.assertIn(b"capivara-tls-resilient", response)
            finally:
                stalled.close()
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
