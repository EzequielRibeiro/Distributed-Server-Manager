#!/usr/bin/env python3
from __future__ import annotations

import socket
import struct
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / "agents" / "common"

if str(COMMON) not in sys.path:
    sys.path.insert(0, str(COMMON))

from source_rcon import SourceRconError, execute


def packet(request_id: int, packet_type: int, body: str) -> bytes:
    payload = (
        struct.pack("<ii", request_id, packet_type)
        + body.encode()
        + b"\x00\x00"
    )
    return struct.pack("<i", len(payload)) + payload


def read_packet(conn):
    size = struct.unpack("<i", conn.recv(4))[0]
    data = bytearray()

    while len(data) < size:
        data.extend(conn.recv(size - len(data)))

    request_id, packet_type = struct.unpack("<ii", data[:8])
    return request_id, packet_type, bytes(data[8:-2]).decode()


class SourceRconProtocolTest(unittest.TestCase):

    def test_auth_and_execute(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)

        port = listener.getsockname()[1]
        observed = {}

        def server():
            conn, _ = listener.accept()

            with conn:
                rid, typ, body = read_packet(conn)
                observed["auth"] = (rid, typ, body)

                conn.sendall(packet(rid, 2, ""))

                rid, typ, body = read_packet(conn)
                observed["command"] = (rid, typ, body)

                conn.sendall(packet(rid, 0, "OK"))

            listener.close()

        thread = threading.Thread(target=server)
        thread.start()

        result = execute(
            "127.0.0.1",
            port,
            "secret-password",
            "save-all flush",
        )

        thread.join(timeout=2)

        self.assertEqual(result, "OK")
        self.assertEqual(
            observed["auth"][1:],
            (3, "secret-password"),
        )
        self.assertEqual(
            observed["command"][1:],
            (2, "save-all flush"),
        )

    def test_auth_failure_is_rejected(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]

        def server():
            conn, _ = listener.accept()
            with conn:
                read_packet(conn)
                conn.sendall(packet(-1, 2, ""))
            listener.close()

        thread = threading.Thread(target=server)
        thread.start()

        with self.assertRaisesRegex(
            SourceRconError,
            "authentication failed",
        ):
            execute(
                "127.0.0.1",
                port,
                "wrong",
                "save-all flush",
            )

        thread.join(timeout=2)

    def test_remote_destination_is_rejected(self):
        with self.assertRaisesRegex(
            SourceRconError,
            "must be local",
        ):
            execute(
                "192.0.2.10",
                25575,
                "secret",
                "save-all flush",
            )


if __name__ == "__main__":
    unittest.main()
