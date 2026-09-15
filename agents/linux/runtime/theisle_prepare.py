#!/usr/bin/env python3
"""Prepare The Isle Evrima ephemeral config without persisting EOS secrets."""
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

def _root(value: str, label: str) -> Path:
    root=Path(value)
    if not root.is_absolute() or not root.is_dir() or root.is_symlink(): raise SystemExit(f"{label} is invalid")
    return root.resolve()

def _copy_game_ini(persistent: Path, runtime: Path) -> None:
    source=persistent/"Game.ini"
    if not source.exists(): return
    if source.is_symlink() or not source.is_file(): raise SystemExit("persistent Game.ini is invalid")
    content=source.read_text(encoding="utf-8")
    target=runtime/"Game.ini";temp=runtime/".Game.ini.tmp"
    temp.write_text(content,encoding="utf-8");os.chmod(temp,0o600);os.replace(temp,target)

def main() -> int:
    parser=argparse.ArgumentParser();parser.add_argument("--runtime-config-root",required=True);parser.add_argument("--persistent-config-root",required=True);args=parser.parse_args()
    root=_root(args.runtime_config_root,"runtime config root");persistent=_root(args.persistent_config_root,"persistent config root")
    _copy_game_ini(persistent,root)
    client_id=_credential("EOS_CLIENT_ID");client_secret=_credential("EOS_CLIENT_SECRET")
    content=("[/Script/OnlineSubsystemEOS.NetDriverEOS]\n""bIsUsingP2PSockets=True\n\n""[OnlineSubsystemEOS]\n""bEnabled=True\n"f"ClientId={client_id}\n"f"ClientSecret={client_secret}\n")
    target=root/"Engine.ini";temp=root/".Engine.ini.tmp";temp.write_text(content,encoding="utf-8");os.chmod(temp,0o600);os.replace(temp,target);return 0
if __name__=="__main__": raise SystemExit(main())
