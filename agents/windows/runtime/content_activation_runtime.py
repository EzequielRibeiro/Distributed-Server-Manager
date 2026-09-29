#!/usr/bin/env python3
"""Agent-local Universal Content activation -> runtime projection.

Game-specific semantics stay on the Agent. The resulting runtime fields are
command-free and generic: process arguments plus confined configuration
properties. Controller/Dashboard never render game-specific activation.
"""
from __future__ import annotations
import re
from pathlib import Path
from typing import Any

try:
 from content_activation_dayz import DayZContentActivationError,project_dayz_activation,project_dayz_community_maps
except ModuleNotFoundError as exc:
 if exc.name != "content_activation_dayz":raise
 import importlib.util
 _dayz_path=Path(__file__).with_name("content_activation_dayz.py")
 _dayz_spec=importlib.util.spec_from_file_location(f"{__name__}_dayz",_dayz_path)
 if _dayz_spec is None or _dayz_spec.loader is None:raise
 _dayz_module=importlib.util.module_from_spec(_dayz_spec);_dayz_spec.loader.exec_module(_dayz_module)
 DayZContentActivationError=_dayz_module.DayZContentActivationError
 project_dayz_activation=_dayz_module.project_dayz_activation
 project_dayz_community_maps=_dayz_module.project_dayz_community_maps
try:
 from content_activation_palworld import PalworldContentActivationError,materialize_palworld_settings,project_palworld_activation
except ModuleNotFoundError as exc:
 if exc.name != "content_activation_palworld":raise
 import importlib.util
 _palworld_path=Path(__file__).with_name("content_activation_palworld.py")
 _palworld_spec=importlib.util.spec_from_file_location(f"{__name__}_palworld",_palworld_path)
 if _palworld_spec is None or _palworld_spec.loader is None:raise
 _palworld_module=importlib.util.module_from_spec(_palworld_spec);_palworld_spec.loader.exec_module(_palworld_module)
 PalworldContentActivationError=_palworld_module.PalworldContentActivationError
 materialize_palworld_settings=_palworld_module.materialize_palworld_settings
 project_palworld_activation=_palworld_module.project_palworld_activation
try:
 from content_activation_minecraft import MinecraftContentActivationError,materialize_minecraft_files,materialize_minecraft_overrides,project_minecraft_bundle_overrides,project_minecraft_files
except ModuleNotFoundError as exc:
 if exc.name != "content_activation_minecraft":raise
 import importlib.util
 _minecraft_path=Path(__file__).with_name("content_activation_minecraft.py")
 _minecraft_spec=importlib.util.spec_from_file_location(f"{__name__}_minecraft",_minecraft_path)
 if _minecraft_spec is None or _minecraft_spec.loader is None:raise
 _minecraft_module=importlib.util.module_from_spec(_minecraft_spec);_minecraft_spec.loader.exec_module(_minecraft_module)
 MinecraftContentActivationError=_minecraft_module.MinecraftContentActivationError
 materialize_minecraft_files=_minecraft_module.materialize_minecraft_files
 materialize_minecraft_overrides=_minecraft_module.materialize_minecraft_overrides
 project_minecraft_bundle_overrides=_minecraft_module.project_minecraft_bundle_overrides
 project_minecraft_files=_minecraft_module.project_minecraft_files

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
 game_id=str(result.get("game_id") or "").strip().lower();dayz_enabled=not (game_id=="dayz" and result.get("dayz_content_enabled") is False)
 if game_id=="dayz":result["dayz_content_enabled"]=dayz_enabled
 if game_id=="dayz" and not dayz_enabled:base=[value for value in base if not str(value).strip().lower().startswith(("-mod=","-servermod="))]
 dayz_map_entries=[entry for entry in entries if _adapter(entry)=="dayz" and str(entry.get("content_type") or "").strip().lower()=="map"]
 dayz_entries=[entry for entry in entries if _adapter(entry)=="dayz" and str(entry.get("content_type") or "").strip().lower()!="map"] if dayz_enabled else []
 try:
  community_missions=project_dayz_community_maps(result,dayz_map_entries) if game_id=="dayz" else []
 except DayZContentActivationError as exc:raise ContentRuntimeActivationError(str(exc)) from exc
 if community_missions:result["content_dayz_community_missions"]=community_missions
 else:result.pop("content_dayz_community_missions",None)
 if dayz_entries:
  try:dayz=project_dayz_activation(result,dayz_entries)
  except DayZContentActivationError as exc:raise ContentRuntimeActivationError(str(exc)) from exc
  if dayz["key_sources"]:
   raise ContentRuntimeActivationError("DayZ Workshop signature keys cannot be isolated safely by the Windows Agent")
  content_args.extend(dayz["arguments"])
 args,props=_project_zomboid(entries);content_args.extend(args);properties.extend(props)
 palworld_entries=[entry for entry in entries if _adapter(entry)=="palworld"]
 if str(result.get("game_id") or "").strip().lower()=="palworld":
  try:
   palworld=project_palworld_activation(result,palworld_entries)
  except PalworldContentActivationError as exc:raise ContentRuntimeActivationError(str(exc)) from exc
  content_args.extend(palworld["arguments"])
  result["content_palworld_packages"]=list(palworld["packages"])
  result["content_palworld_workshop_root"]=palworld["workshop_root"]
 result["content_base_arguments"]=[str(v) for v in base]
 result["arguments"]=[*result["content_base_arguments"],*content_args]
 result["content_configuration_properties"]=properties
 try:
  result["content_file_projections"]=project_minecraft_files(result,entries);result["content_bundle_overrides"]=project_minecraft_bundle_overrides(result,entries)
 except MinecraftContentActivationError as exc:raise ContentRuntimeActivationError(str(exc)) from exc
 result["content_activation_checksum"]=str(snapshot.get("checksum") or "")
 return result

def _configuration_root(spec:dict[str,Any])->Path:
 raw=spec.get("instance_state_root") or spec.get("configuration_root") or spec.get("working_directory") or spec.get("path")
 if not raw:raise ContentRuntimeActivationError("content activation has no configuration root")
 return Path(str(raw)).resolve()

def materialize_content_activation(spec:dict[str,Any])->list[str]:
 props=spec.get("content_configuration_properties") if isinstance(spec.get("content_configuration_properties"),list) else []
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
 try:
  written.extend(materialize_palworld_settings(spec));written.extend(materialize_minecraft_files(spec));written.extend(materialize_minecraft_overrides(spec))
 except (PalworldContentActivationError,MinecraftContentActivationError) as exc:raise ContentRuntimeActivationError(str(exc)) from exc
 return written

__all__=["ContentRuntimeActivationError","materialize_content_activation","project_runtime_spec"]
