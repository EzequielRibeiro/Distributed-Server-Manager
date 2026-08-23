#!/usr/bin/env python3
"""Safe file operations confined to one resolved Windows Agent game-data root."""
from __future__ import annotations
import base64, os, shutil
from pathlib import Path
from typing import Any
MAX_TEXT_BYTES=1024*1024
MAX_UPLOAD_BYTES=32*1024*1024

def _relative(value:Any,*,allow_root:bool=True)->Path:
 text=str(value or "").strip().replace("\\","/")
 if not text:
  if allow_root:return Path(".")
  raise ValueError("path is required")
 p=Path(text)
 if p.is_absolute() or ".." in p.parts:raise ValueError("path must be relative to game-data root")
 return p

def _resolve(root:Path,value:Any,*,allow_root:bool=True,must_exist:bool=False)->Path:
 root=root.resolve(); rel=_relative(value,allow_root=allow_root); target=(root/rel).resolve(strict=False)
 try:target.relative_to(root)
 except ValueError as exc:raise ValueError("path escapes game-data root") from exc
 cursor=root
 for part in rel.parts:
  if part in {"","."}:continue
  cursor=cursor/part
  if cursor.exists() and cursor.is_symlink():
   try:cursor.resolve().relative_to(root)
   except ValueError as exc:raise ValueError("symlink escapes game-data root") from exc
 if must_exist and not target.exists():raise FileNotFoundError(str(rel))
 return target

def _entry(root:Path,path:Path)->dict[str,Any]:
 stat=path.lstat(); rel=path.relative_to(root).as_posix()
 return {"name":path.name,"path":"" if rel=="." else rel,"type":"directory" if path.is_dir() else "file","size":stat.st_size if path.is_file() else None,"modified_ns":stat.st_mtime_ns,"writable":os.access(path,os.W_OK)}
def execute_file_operation(root:Path,operation:dict[str,Any])->dict[str,Any]:
 root=root.resolve()
 if not root.is_dir():raise RuntimeError("game-data is not installed")
 action=str(operation.get("action") or "").strip().lower(); path=operation.get("path")
 if action=="list":
  d=_resolve(root,path,must_exist=True)
  if not d.is_dir():raise ValueError("path is not a directory")
  return {"operation":action,"path":"" if d==root else d.relative_to(root).as_posix(),"entries":[_entry(root,p) for p in sorted(d.iterdir(),key=lambda p:(not p.is_dir(),p.name.lower()))][:2000]}
 if action=="read":
  t=_resolve(root,path,allow_root=False,must_exist=True)
  if not t.is_file():raise ValueError("path is not a file")
  if t.stat().st_size>MAX_TEXT_BYTES:raise ValueError("file exceeds editable text limit")
  raw=t.read_bytes()
  if b"\x00" in raw:raise ValueError("binary files cannot be edited as text")
  return {"operation":action,"path":t.relative_to(root).as_posix(),"content":raw.decode("utf-8"),"size":len(raw)}
 if action in {"write","create"}:
  t=_resolve(root,path,allow_root=False);t.parent.mkdir(parents=True,exist_ok=True)
  if action=="create" and t.exists():raise FileExistsError(str(path))
  raw=str(operation.get("content") or "").encode("utf-8")
  if len(raw)>MAX_TEXT_BYTES:raise ValueError("content exceeds editable text limit")
  temp=t.with_name(t.name+".capivara-tmp");temp.write_bytes(raw);temp.replace(t)
  return {"operation":action,"path":t.relative_to(root).as_posix(),"size":len(raw),"modified":True}
 if action=="mkdir":
  t=_resolve(root,path,allow_root=False);t.mkdir(parents=True,exist_ok=False);return {"operation":action,"path":t.relative_to(root).as_posix(),"modified":True}
 if action=="rename":
  src=_resolve(root,path,allow_root=False,must_exist=True);dst=_resolve(root,operation.get("destination"),allow_root=False)
  if dst.exists():raise FileExistsError(str(operation.get("destination") or ""))
  dst.parent.mkdir(parents=True,exist_ok=True);src.rename(dst);return {"operation":action,"path":src.relative_to(root).as_posix(),"destination":dst.relative_to(root).as_posix(),"modified":True}
 if action=="delete":
  t=_resolve(root,path,allow_root=False,must_exist=True);rel=t.relative_to(root).as_posix()
  if t.is_dir():
   if any(t.iterdir()) and not bool(operation.get("recursive")):raise ValueError("directory is not empty")
   shutil.rmtree(t)
  else:t.unlink()
  return {"operation":action,"path":rel,"modified":True}
 if action=="upload":
  t=_resolve(root,path,allow_root=False)
  try:raw=base64.b64decode(str(operation.get("content_base64") or ""),validate=True)
  except Exception as exc:raise ValueError("invalid base64 upload") from exc
  if len(raw)>MAX_UPLOAD_BYTES:raise ValueError("upload exceeds size limit")
  t.parent.mkdir(parents=True,exist_ok=True);tmp=t.with_name(t.name+".capivara-upload");tmp.write_bytes(raw);tmp.replace(t)
  return {"operation":action,"path":t.relative_to(root).as_posix(),"size":len(raw),"modified":True}
 raise ValueError("unsupported game-data file operation")

__all__=["MAX_TEXT_BYTES","MAX_UPLOAD_BYTES","execute_file_operation"]
