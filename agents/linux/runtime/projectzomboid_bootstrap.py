#!/usr/bin/env python3
"""One-shot Project Zomboid first-start bootstrap without persisting an admin credential.

Project Zomboid requires the initial admin password twice on stdin when no admin
account exists. Capivara generates a high-entropy throw-away credential locally,
feeds it only through the child's stdin, then discards it. The credential is never
placed in argv, environment, provisioning JSON, systemd units, results, or logs.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import secrets
import subprocess
import sys


def _safe_servername(value: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 64 or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for ch in text):
        raise ValueError("invalid Project Zomboid server name")
    return text


def _safe_port(value: int) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise ValueError("invalid Project Zomboid game port")
    return port


def _marker(home: Path, servername: str) -> Path:
    return home / ".capivara" / f"projectzomboid-bootstrap-{servername}.v1"


def bootstrap(*, servername: str, port: int, timeout_seconds: int = 900) -> bool:
    servername = _safe_servername(servername)
    port = _safe_port(port)
    home = Path(os.environ.get("HOME") or "").resolve()
    if not home.is_absolute() or str(home) == "/":
        raise RuntimeError("Project Zomboid bootstrap requires a private HOME")
    marker = _marker(home, servername)
    if marker.is_file():
        return False

    working = Path.cwd().resolve()
    launcher = (working / "start-server.sh").resolve()
    try:
        launcher.relative_to(working)
    except ValueError as exc:
        raise RuntimeError("Project Zomboid launcher escapes working directory") from exc
    if not launcher.is_file():
        raise RuntimeError("Project Zomboid start-server.sh is unavailable")

    password = secrets.token_urlsafe(36)
    stdin_payload = f"{password}\n{password}\nquit\n"
    completed = subprocess.run(
        [str(launcher), "-servername", servername, "-port", str(port)],
        input=stdin_payload,
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=dict(os.environ),
        cwd=str(working),
        check=False,
        timeout=max(60, min(int(timeout_seconds), 1800)),
    )
    password = ""
    stdin_payload = ""
    if completed.returncode != 0:
        raise RuntimeError(f"Project Zomboid first-start bootstrap failed with exit code {completed.returncode}")

    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("completed\n", encoding="utf-8")
    os.chmod(marker.parent, 0o700)
    os.chmod(marker, 0o600)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--servername", default="servertest")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    try:
        bootstrap(servername=args.servername, port=args.port)
        return 0
    except Exception as exc:
        print(f"Project Zomboid bootstrap failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
