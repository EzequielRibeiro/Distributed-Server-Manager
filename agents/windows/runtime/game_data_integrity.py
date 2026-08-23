#!/usr/bin/env python3
"""Bounded game-data integrity inventory for Windows Agent."""
from __future__ import annotations
import hashlib
from pathlib import Path
from typing import Any
MAX_INVENTORY_FILES=200000
def inspect_game_data(root:Path,selection:dict[str,Any]|None=None)->dict[str,Any]:
 root=Path(root).resolve()
 if not root.is_dir():return {"health":"missing","exists":False,"files":0,"bytes":0}
 digest=hashlib.sha256();files=0;total=0;truncated=False
 for path in sorted(root.rglob("*")):
  if path.is_symlink():
   try:path.resolve().relative_to(root)
   except ValueError:return {"health":"unsafe","exists":True,"files":files,"bytes":total,"reason":"symlink_escape"}
   continue
  if not path.is_file():continue
  files+=1
  if files>MAX_INVENTORY_FILES:truncated=True;break
  stat=path.stat();total+=stat.st_size;digest.update(path.relative_to(root).as_posix().encode());digest.update(b"\0");digest.update(str(stat.st_size).encode());digest.update(b"\n")
 executable=str((selection or {}).get("executable") or "").strip();present=True
 if executable:
  candidate=Path(executable);candidate=candidate if candidate.is_absolute() else root/candidate
  try:candidate.resolve().relative_to(root);present=candidate.is_file()
  except ValueError:present=False
 health="ok" if files and present and not truncated else ("degraded" if files else "empty")
 return {"health":health,"exists":True,"files":min(files,MAX_INVENTORY_FILES),"bytes":total,"tree_digest":digest.hexdigest(),"truncated":truncated,"executable_present":present}
__all__=["MAX_INVENTORY_FILES","inspect_game_data"]
