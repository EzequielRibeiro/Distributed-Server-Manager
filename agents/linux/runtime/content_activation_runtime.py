#!/usr/bin/env python3
"""Agent-local Universal Content activation -> runtime projection.

Game-specific semantics stay on the Agent. The resulting runtime fields are
command-free and generic: process arguments plus confined configuration
properties. Controller/Dashboard never render game-specific activation.
"""
from __future__ import annotations
import os,re
from pathlib import Path
from typing import Any

_SAFE_ID=re.compile(r"^[A-Za-z0-9._-]{1,191}$")
_SAFE_MOD_ID=re.compile(r"^[^;\r\n]{1,191}$")

class ContentRuntimeActivationError(RuntimeError):pass

def _entries(snapshot:dict[str,Any])->list[dict[str,Any]]:
 values=snapshot.get("entries") if isinstance(snapshot,dict) else []
 if not isinstance(values,list):raise ContentRuntimeActivationError("invalid activation snapshot")
 return [dict(v) for v in values if isinstance(v,dict)]

def _adapter(entry:dict[str,Any])->str:
 game=str(entry.get("game_id") or "").strip().lower();declared=str((entry.get("activation") or {}).get("adapter") or "").strip().lower()
 canonical={"dayz":"dayz","projectzomboid":"project-zomboid"}.get(game,"")
 if declared and canonical and declared!=canonical:raise ContentRuntimeActivationError("content activation adapter does not match game")
 return canonical or declared

def _managed_path(entry:dict[str,Any])->str:
 value=str(entry.get("managed_path") or "").strip()
 if not value or not os.path.isabs(value) or any(c in value for c in ("\x00","\r","\n",";")):raise ContentRuntimeActivationError("invalid managed content path")
 return str(Path(value))

def _dayz(entries:list[dict[str,Any]])->tuple[list[str],list[dict[str,str]]]:
 mods=[];server=[]
 for entry in entries:
  if _adapter(entry)!="dayz":continue
  mode=str((entry.get("activation") or {}).get("mode") or "mod").strip().lower();path=_managed_path(entry)
  if mode=="mod":mods.append(path)
  elif mode=="server-mod":server.append(path)
  else:raise ContentRuntimeActivationError("unsupported DayZ content activation mode")
 args=[]
 if mods:args.append("-mod="+";".join(mods))
 if server:args.append("-serverMod="+";".join(server))
 return args,[]

def _project_zomboid(entries:list[dict[str,Any]])->tuple[list[str],list[dict[str,str]]]:
 workshop=[];mods=[]
 for entry in entries:
  if _adapter(entry)!="project-zomboid":continue
  package=str(entry.get("package_id") or "").strip();parts=package.split(":",1)
  if len(parts)!=2 or parts[0]!="108600" or not parts[1].isdigit():raise ContentRuntimeActivationError("invalid Project Zomboid Workshop package")
  identifier=str((entry.get("activation") or {}).get("identifier") or "").strip()
  if not _SAFE_MOD_ID.fullmatch(identifier):raise ContentRuntimeActivationError("Project Zomboid content requires a safe activation identifier")
  if parts[1] not in workshop:workshop.append(parts[1])
  if identifier not in mods:mods.append(identifier)
 props=[]
 if workshop:props.append({"path":"Zomboid/Server/servertest.ini","key":"WorkshopItems","value":";".join(workshop),"syntax":"equals"})
 if mods:props.append({"path":"Zomboid/Server/servertest.ini","key":"Mods","value":";".join(mods),"syntax":"equals"})
 return [],props

def project_runtime_spec(spec:dict[str,Any],snapshot:dict[str,Any])->dict[str,Any]:
 result=dict(spec);entries=_entries(snapshot);games={str(e.get("game_id") or "").strip().lower() for e in entries if e.get("game_id")}
 if len(games)>1:raise ContentRuntimeActivationError("activation snapshot mixes games")
 base=list(result.get("content_base_arguments") if isinstance(result.get("content_base_arguments"),list) else result.get("arguments") or [])
 content_args=[];properties=[]
 for renderer in (_dayz,_project_zomboid):
  args,props=renderer(entries);content_args.extend(args);properties.extend(props)
 result["content_base_arguments"]=[str(v) for v in base]
 result["arguments"]=[*result["content_base_arguments"],*content_args]
 result["content_configuration_properties"]=properties
 result["content_activation_checksum"]=str(snapshot.get("checksum") or "")
 return result

def _configuration_root(spec:dict[str,Any])->Path:
 raw=spec.get("instance_state_root") or spec.get("configuration_root") or spec.get("working_directory") or spec.get("path")
 if not raw:raise ContentRuntimeActivationError("content activation has no configuration root")
 return Path(str(raw)).resolve()

def materialize_content_activation(spec:dict[str,Any])->list[str]:
 props=spec.get("content_configuration_properties") if isinstance(spec.get("content_configuration_properties"),list) else []
 if not props:return []
 root=_configuration_root(spec);written=[]
 for item in props:
  if not isinstance(item,dict):raise ContentRuntimeActivationError("invalid content configuration property")
  relative=Path(str(item.get("path") or ""))
  if not str(relative) or relative.is_absolute() or ".." in relative.parts:raise ContentRuntimeActivationError("invalid content configuration path")
  target=(root/relative).resolve()
  try:target.relative_to(root)
  except ValueError as exc:raise ContentRuntimeActivationError("content configuration path escapes instance") from exc
  if target.is_symlink():raise ContentRuntimeActivationError("content configuration file cannot be a symbolic link")
  key=str(item.get("key") or "").strip();value=str(item.get("value") or "")
  if not _SAFE_ID.fullmatch(key) or any(c in value for c in ("\x00","\r","\n")):raise ContentRuntimeActivationError("invalid content configuration value")
  text=target.read_text(encoding="utf-8",errors="replace") if target.exists() else ""
  pattern=re.compile(rf"(?m)^\s*{re.escape(key)}\s*=\s*[^\r\n]*$");line=f"{key}={value}"
  text=pattern.sub(line,text,count=1) if pattern.search(text) else text.rstrip("\n")+("\n" if text else "")+line+"\n"
  target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text,encoding="utf-8");written.append(relative.as_posix())
 return written

__all__=["ContentRuntimeActivationError","materialize_content_activation","project_runtime_spec"]
