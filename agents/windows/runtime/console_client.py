#!/usr/bin/env python3
"""Trusted game-console transport for the Windows Agent."""
from __future__ import annotations

from datetime import datetime, timezone
import json, os, re, sys
from pathlib import Path
import subprocess
from typing import Any

_HERE=Path(__file__).resolve()
_COMMON_CANDIDATES=(
    _HERE.parents[2]/"common",
    _HERE.parents[1]/"common",
)
COMMON=next((path for path in _COMMON_CANDIDATES if path.is_dir()),_COMMON_CANDIDATES[0])
if str(COMMON) not in sys.path:sys.path.insert(0,str(COMMON))

import instance_runtime
from source_rcon import SourceRconError, execute as execute_source_rcon
from minecraft_rcon_secret import MinecraftRconSecretError, read_password

PROGRAM_DATA=Path(os.environ.get("PROGRAMDATA",r"C:\ProgramData"))
STATE_DIR=Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR",PROGRAM_DATA/"CapivaraAgent"/"state"))
RESULT_DIR=STATE_DIR/"console-results";HISTORY_DIR=STATE_DIR/"console-history";PROCESS_LOG_DIR=STATE_DIR/"runtime-processes"/"logs";_INSTANCE_RE=re.compile(r"^[A-Za-z0-9._-]{1,191}$")

def _now():return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
def _path(root,command_id):
 safe="".join(c for c in str(command_id or "") if c.isalnum() or c in "._-")
 if not safe or len(safe)>191:raise ValueError("invalid console command id")
 return root/f"{safe}.json"
def _read(path):
 try:value=json.loads(path.read_text(encoding="utf-8"))
 except (OSError,ValueError):return None
 return value if isinstance(value,dict) else None
def _write(path,payload):
 path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix(".tmp");temp.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8");os.replace(temp,path)
def _tail(path_value,limit=120):
 path=Path(str(path_value or ""))
 if not path.is_file():return []
 try:return path.read_text(encoding="utf-8",errors="replace").splitlines()[-limit:]
 except OSError:return []
def _snapshot_output(record,console):
 instance_id=str(record.get("instance_id") or "").strip();adapter=str(record.get("adapter") or "").strip().lower()
 if adapter=="windows-process" and _INSTANCE_RE.fullmatch(instance_id):return "windows-process-log",_tail(PROCESS_LOG_DIR/f"{instance_id}.log",200)
 raw=str(console.get("output_file") or "").strip()
 if raw:
  try:
   root=STATE_DIR.resolve(strict=False);candidate=Path(raw).resolve(strict=False);candidate.relative_to(root)
  except (OSError,ValueError):candidate=None
  if candidate is not None:return str(console.get("transport") or "configured-output"),_tail(candidate,200)
 return None,[]
def _resolved_console(record):
 console=record.get("console") if isinstance(record.get("console"),dict) else {}
 if bool(console.get("supported")):return console
 game=str(record.get("game_id") or "").strip().lower()
 environment_id=str(record.get("environment_id") or "").strip().lower()
 rcon=(record.get("ports") or {}).get("rcon") or {}
 if game=="minecraft" and environment_id.startswith("minecraft.java.") and rcon.get("port"):
  return {"supported":True,"transport":"minecraft-rcon","timeout_seconds":5}
 return console

def _minecraft_rcon_transport(record,console,command):
 game=str(record.get("game_id") or "").strip().lower()
 environment_id=str(record.get("environment_id") or "").strip().lower()
 if game!="minecraft" or not environment_id.startswith("minecraft.java."):raise RuntimeError("minecraft RCON transport requires Minecraft Java")
 try:
  password=read_password(record)
  rcon=(record.get("ports") or {}).get("rcon") or {}
  port=int(rcon.get("port") or 0)
  timeout=max(1.0,min(float(console.get("timeout_seconds") or 5),30.0))
  output=execute_source_rcon("127.0.0.1",port,password,command,timeout=timeout)
 except (MinecraftRconSecretError,SourceRconError,TypeError,ValueError) as exc:
  raise RuntimeError(str(exc)) from exc
 return output.splitlines() if output else []

def execute(config:dict[str,Any],instance_id:str,command:str)->list[str]:
 record=instance_runtime.get_instance(instance_id)
 if not isinstance(record,dict):raise LookupError("instance not found")
 if str(record.get("agent_id") or "")!=str(config.get("agent_id") or ""):raise PermissionError("instance belongs to another Agent")
 console=_resolved_console(record)
 if not bool(console.get("supported")):raise RuntimeError("runtime does not support game console")
 command=str(command or "").strip()
 if not command or len(command)>512 or any(x in command for x in ("\x00","\n","\r")):raise ValueError("invalid game console command")
 transport=str(console.get("transport") or "").lower()
 if transport=="minecraft-rcon":return _minecraft_rcon_transport(record,console,command)
 if transport!="exec":raise RuntimeError(f"unsupported Windows game console transport: {transport or 'none'}")
 template=console.get("command_argv")
 if not isinstance(template,list) or not template or not all(isinstance(x,str) for x in template):raise RuntimeError("console exec transport has no trusted command_argv")
 executable=Path(template[0])
 if not executable.is_absolute():raise RuntimeError("console executable must use an absolute path")
 if sum(item.count("{command}") for item in template)!=1:raise RuntimeError("console command_argv must contain one {command} placeholder")
 argv=[item.replace("{command}",command) for item in template]
 result=subprocess.run(argv,capture_output=True,text=True,check=False,timeout=max(1,min(int(console.get("timeout_seconds") or 10),30)),creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
 output=[]
 if result.stdout:output.extend(result.stdout.rstrip().splitlines())
 if result.stderr:output.extend(result.stderr.rstrip().splitlines())
 if result.returncode!=0:raise RuntimeError(("\n".join(output) or f"console transport failed ({result.returncode})")[:2000])
 return output[-200:]
def handle_command(config,command):
 command_id=str(command.get("command_id") or "").strip();history=_path(HISTORY_DIR,command_id);previous=_read(history)
 if previous is not None:_write(_path(RESULT_DIR,command_id),previous);return previous
 instance_id=str(command.get("instance_id") or "").strip();text=str(command.get("command_text") or "")
 try:result={"command_id":command_id,"instance_id":instance_id,"status":"completed","output":execute(config,instance_id,text),"generated_at":_now()}
 except Exception as exc:result={"command_id":command_id,"instance_id":instance_id or None,"status":"failed","error":str(exc)[:2000],"generated_at":_now()}
 _write(history,result);_write(_path(RESULT_DIR,command_id),result);return result
def read_result():
 try:paths=sorted(RESULT_DIR.glob("*.json"))
 except OSError:paths=[]
 for path in paths:
  value=_read(path)
  if value:return value
 return None
def clear_result(command_id):
 try:_path(RESULT_DIR,command_id).unlink()
 except FileNotFoundError:pass
def console_state(config):
 result=[]
 for item in instance_runtime.list_instances(config):
  record=instance_runtime.get_instance(str(item.get("instance_id") or "")) or {};console=_resolved_console(record);transport,output=_snapshot_output(record,console)
  if transport is not None or bool(console.get("supported")):result.append({"instance_id":record.get("instance_id"),"supported":bool(console.get("supported")),"transport":transport or console.get("transport"),"output":output})
 return result
__all__=["clear_result","console_state","execute","handle_command","read_result"]
