"""Atomic Windows Agent-local state for Storage Pool operations."""
from __future__ import annotations
import json,os
from pathlib import Path
from typing import Any
PROGRAM_DATA=Path(os.environ.get("PROGRAMDATA",r"C:\ProgramData"));STATE_DIR=Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR",PROGRAM_DATA/"CapivaraAgent"/"state"));MIGRATION_ROOT=STATE_DIR/"storage-pool-migrations";HISTORY_ROOT=MIGRATION_ROOT/"history"
def safe_id(value:Any,label:str="migration_id")->str:
 text=str(value or "").strip();allowed="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
 if not text or len(text)>191 or any(ch not in allowed for ch in text):raise ValueError(f"invalid {label}")
 return text
def paths(migration_id:str):
 token=safe_id(migration_id);return MIGRATION_ROOT/f"{token}.request.json",MIGRATION_ROOT/f"{token}.result.json",MIGRATION_ROOT/f"{token}.log"
def read_json(path:Path):
 try:value=json.loads(path.read_text(encoding="utf-8"))
 except (OSError,ValueError):return None
 return value if isinstance(value,dict) else None
def write_json(path:Path,payload:dict[str,Any]):
 path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_name(f".{path.name}.{os.getpid()}.tmp");temp.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8");os.replace(temp,path)
def archive(migration_id:str):
 req,res,log=paths(migration_id);HISTORY_ROOT.mkdir(parents=True,exist_ok=True)
 for source in (req,res,log):
  if source.exists():
   try:os.replace(source,HISTORY_ROOT/source.name)
   except OSError:pass
__all__=["HISTORY_ROOT","MIGRATION_ROOT","archive","paths","read_json","safe_id","write_json"]
