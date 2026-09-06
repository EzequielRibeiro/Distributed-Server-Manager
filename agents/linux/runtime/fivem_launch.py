#!/usr/bin/env python3
"""Launch FiveM with the Cfx.re license key read from a systemd credential."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _fail(message: str) -> None:
    raise SystemExit(message)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 6 or args[0] != "--server" or args[2] != "--data" or args[4] != "--license-credential":
        _fail("invalid FiveM launcher arguments")
    server = Path(args[1])
    data = Path(args[3])
    credential = args[5]
    extra = args[6:]
    if not server.is_absolute() or not server.is_file():
        _fail("FiveM run.sh is unavailable")
    if not data.is_absolute() or not data.is_dir():
        _fail("FiveM server-data directory is unavailable")
    if any("\x00" in value or "\n" in value or "\r" in value for value in extra):
        _fail("invalid FiveM runtime argument")
    credentials = os.environ.get("CREDENTIALS_DIRECTORY", "")
    if not credentials:
        _fail("systemd credentials directory is unavailable")
    path = Path(credentials) / credential
    try:
        license_key = path.read_text(encoding="utf-8").rstrip("\r\n")
    except OSError as exc:
        _fail(f"FiveM license credential is unavailable: {exc}")
    if not license_key or len(license_key) > 512 or any(c in license_key for c in ("\x00", "\n", "\r")):
        _fail("FiveM license credential is invalid")
    os.chdir(data)
    os.execv(str(server), [str(server), "+exec", "server.cfg", "+set", "sv_licenseKey", license_key, *extra])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
