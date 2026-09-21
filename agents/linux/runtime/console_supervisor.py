#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading

MAX_COMMAND_BYTES = 4096


def serve_console(
    listener: socket.socket,
    process: subprocess.Popen,
) -> None:
    while process.poll() is None:
        try:
            connection, _ = listener.accept()
        except OSError:
            return

        with connection:
            data = bytearray()

            while len(data) <= MAX_COMMAND_BYTES:
                chunk = connection.recv(
                    min(
                        1024,
                        MAX_COMMAND_BYTES + 1 - len(data),
                    )
                )

                if not chunk:
                    break

                data.extend(chunk)

                if b"\n" in data:
                    data = data.split(b"\n", 1)[0]
                    break

            if (
                not data
                or len(data) > MAX_COMMAND_BYTES
                or b"\x00" in data
                or b"\r" in data
            ):
                connection.sendall(b"ERROR invalid command\n")
                continue

            try:
                command = data.decode("utf-8")
            except UnicodeDecodeError:
                connection.sendall(b"ERROR invalid utf-8\n")
                continue

            if process.stdin is None:
                connection.sendall(b"ERROR stdin unavailable\n")
                continue

            try:
                process.stdin.write(command + "\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError):
                connection.sendall(b"ERROR server stdin closed\n")
                continue

            connection.sendall(b"OK\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    command = list(args.command)

    if command and command[0] == "--":
        command = command[1:]

    if not command:
        raise SystemExit("server command is required")

    socket_path = Path(args.socket)

    socket_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:
        socket_path.unlink()
    except FileNotFoundError:
        pass

    listener = socket.socket(
        socket.AF_UNIX,
        socket.SOCK_STREAM,
    )

    listener.bind(str(socket_path))
    os.chmod(socket_path, 0o600)
    listener.listen(4)

    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    def forward(signum, _frame):
        if process.poll() is None:
            try:
                process.send_signal(signum)
            except ProcessLookupError:
                pass

    signal.signal(signal.SIGTERM, forward)
    signal.signal(signal.SIGINT, forward)

    thread = threading.Thread(
        target=serve_console,
        args=(listener, process),
        daemon=True,
    )
    thread.start()

    try:
        return int(process.wait())
    finally:
        try:
            listener.close()
        except OSError:
            pass

        try:
            socket_path.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
