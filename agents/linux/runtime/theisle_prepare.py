#!/usr/bin/env python3
"""Prepare The Isle Evrima private Engine.ini from systemd credentials."""
from __future__ import annotations
import argparse, os
from pathlib import Path

def _credential(name: str) -> str:
    root = Path(os.environ.get("CREDENTIALS_DIRECTORY", ""))
    if not root.is_absolute(): raise SystemExit("systemd credentials directory is unavailable")
    path = root / name
    if path.is_symlink() or not path.is_file(): raise SystemExit("required runtime credential is unavailable")
    value = path.read_text(encoding="utf-8").strip()
    if not value or any(c in value for c in ("\x00", "\n", "\r")): raise SystemExit("runtime credential is invalid")
    return value

def main() -> int:
    parser=argparse.ArgumentParser();parser.add_argument("--runtime-config-root",required=True);args=parser.parse_args()
    root=Path(args.runtime_config_root)
    if not root.is_absolute() or not root.is_dir() or root.is_symlink(): raise SystemExit("runtime config root is invalid")
    client_id=_credential("EOS_CLIENT_ID");client_secret=_credential("EOS_CLIENT_SECRET")
    content=("[/Script/OnlineSubsystemEOS.NetDriverEOS]\n""bIsUsingP2PSockets=True\n\n""[OnlineSubsystemEOS]\n""bEnabled=True\n"f"ClientId={client_id}\n"f"ClientSecret={client_secret}\n")
    target=root/"Engine.ini";temp=root/".Engine.ini.tmp";temp.write_text(content,encoding="utf-8");os.chmod(temp,0o600);os.replace(temp,target);return 0
if __name__=="__main__": raise SystemExit(main())
