#!/usr/bin/env python3
"""Launch Valheim with its password read only from a systemd credential."""
from __future__ import annotations
import os,sys
from pathlib import Path

def _fail(message:str)->None:
 raise SystemExit(message)

def main(argv:list[str]|None=None)->int:
 args=list(sys.argv[1:] if argv is None else argv)
 if "--" not in args:_fail("Valheim launcher requires -- separator")
 split=args.index("--");control=args[:split];game_args=args[split+1:]
 if len(control)!=4 or control[0]!="--server" or control[2]!="--password-credential":_fail("invalid Valheim launcher arguments")
 server=Path(control[1]);credential=control[3]
 if not server.is_absolute() or not server.is_file():_fail("Valheim server executable is unavailable")
 directory=os.environ.get("CREDENTIALS_DIRECTORY","")
 if not directory:_fail("systemd credentials directory is unavailable")
 path=Path(directory)/credential
 try:password=path.read_text(encoding="utf-8").rstrip("\r\n")
 except OSError as exc:_fail(f"Valheim password credential is unavailable: {exc}")
 if len(password)<5 or any(c in password for c in ("\x00","\n","\r")):_fail("Valheim password credential is invalid")
 os.execv(str(server),[str(server),*game_args,"-password",password])
 return 0

if __name__=="__main__":raise SystemExit(main())
