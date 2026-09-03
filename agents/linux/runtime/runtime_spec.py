#!/usr/bin/env python3
"""Validated Agent-local specification used to materialize instance runtimes."""
from __future__ import annotations
import os,re
from pathlib import Path
from typing import Any
_TOKEN=re.compile(r"^[A-Za-z0-9._-]{1,191}$");_SECRET_NAME=re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
VALID_DESIRED_STATES={"running","stopped"}
class RuntimeSpecError(ValueError):pass
def _token(value:Any,label:str)->str:
 text=str(value or "").strip()
 if not _TOKEN.fullmatch(text):raise RuntimeSpecError(f"invalid {label}")
 return text
def _absolute(value:Any,label:str)->str:
 text=str(value or "").strip()
 if not text or not os.path.isabs(text) or any(c in text for c in ("\x00","\n","\r")):raise RuntimeSpecError(f"invalid {label}")
 return str(Path(text))
def _absolute_list(value:Any,label:str)->list[str]:
 if value is None:return []
 if not isinstance(value,list) or len(value)>128:raise RuntimeSpecError(f"invalid {label}")
 return [_absolute(x,label) for x in value]
def _arguments(value:Any,label:str)->list[str]:
 if value is None:return []
 if not isinstance(value,list) or len(value)>128:raise RuntimeSpecError(f"invalid {label}")
 out=[]
 for item in value:
  text=str(item)
  if any(c in text for c in ("\x00","\n","\r")) or len(text)>4096:raise RuntimeSpecError(f"invalid {label}")
  out.append(text)
 return out
def _pre_start(value:Any)->list[dict[str,Any]]:
 if value is None:return []
 if not isinstance(value,list) or len(value)>8:raise RuntimeSpecError("invalid pre_start")
 out=[]
 for item in value:
  if not isinstance(item,dict):raise RuntimeSpecError("invalid pre_start entry")
  out.append({"executable":_absolute(item.get("executable"),"pre_start executable"),"arguments":_arguments(item.get("arguments",[]),"pre_start arguments")})
 return out
def _secret_refs(value:Any,instance_id:str)->list[dict[str,str]]:
 if value is None:return []
 if not isinstance(value,list) or len(value)>32:raise RuntimeSpecError("invalid secret_refs")
 out=[];seen=set()
 for item in value:
  if not isinstance(item,dict):raise RuntimeSpecError("invalid secret reference")
  name=str(item.get("name") or "").strip();ref=str(item.get("ref") or "").strip();target=str(item.get("target") or "file").strip().lower()
  if not _SECRET_NAME.fullmatch(name) or name in seen:raise RuntimeSpecError("invalid secret reference name")
  if not ref.startswith(f"instance/{instance_id}/") or not _TOKEN.fullmatch(ref.split("/")[-1]):raise RuntimeSpecError("secret reference is outside instance scope")
  if target!="file":raise RuntimeSpecError("unsupported secret target")
  out.append({"name":name,"ref":ref,"target":"file"});seen.add(name)
 return out
def validate_runtime_spec(spec:dict[str,Any],*,expected_agent_id:str|None=None)->dict[str,Any]:
 if not isinstance(spec,dict):raise RuntimeSpecError("runtime spec must be an object")
 result=dict(spec);result["schema_version"]=1;result["kind"]="CapivaraInstanceRuntimeSpec";result["instance_id"]=_token(result.get("instance_id"),"instance_id");result["agent_id"]=_token(result.get("agent_id"),"agent_id")
 if expected_agent_id is not None and result["agent_id"]!=_token(expected_agent_id,"expected_agent_id"):raise RuntimeSpecError("runtime spec belongs to another Agent")
 if result.get("storage_pool_id") is not None:result["storage_pool_id"]=_token(result.get("storage_pool_id"),"storage_pool_id")
 result["runtime_id"]=_token(result.get("runtime_id") or result["instance_id"],"runtime_id");result["adapter"]=_token(result.get("adapter") or "systemd","adapter").lower()
 if result["adapter"]!="systemd":raise RuntimeSpecError("unsupported runtime materialization adapter")
 result["working_directory"]=_absolute(result.get("working_directory") or result.get("path"),"working_directory");result["executable"]=_absolute(result.get("executable"),"executable");result["arguments"]=_arguments(result.get("arguments",[]),"runtime arguments");result["pre_start"]=_pre_start(result.get("pre_start"));result["secret_refs"]=_secret_refs(result.get("secret_refs"),result["instance_id"])
 environment=result.get("environment",{})
 if not isinstance(environment,dict) or len(environment)>128:raise RuntimeSpecError("invalid environment")
 normalized_environment={}
 for key,value in environment.items():
  name=str(key);text=str(value)
  if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}",name) or any(c in text for c in ("\x00","\n","\r")):raise RuntimeSpecError("invalid environment entry")
  normalized_environment[name]=text
 result["environment"]=normalized_environment;user=str(result.get("user") or "capivara-instance").strip()
 if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,63}",user):raise RuntimeSpecError("invalid runtime user")
 result["user"]=user;desired=str(result.get("desired_state") or "stopped").strip().lower()
 if desired not in VALID_DESIRED_STATES:raise RuntimeSpecError("invalid desired_state")
 result["desired_state"]=desired
 for key in ("instance_state_root","configuration_root","config_path"):
  if result.get(key) is not None:result[key]=_absolute(result[key],key)
 result["writable_directories"]=_absolute_list(result.get("writable_directories"),"writable_directories")
 seed=result.get("seed_files") or []
 if not isinstance(seed,list) or len(seed)>128:raise RuntimeSpecError("invalid seed_files")
 result["seed_files"]=[{"source":_absolute(x.get("source"),"seed source"),"target":_absolute(x.get("target"),"seed target")} for x in seed if isinstance(x,dict)]
 if len(result["seed_files"])!=len(seed):raise RuntimeSpecError("invalid seed_files")
 binds=result.get("bind_paths") or []
 if not isinstance(binds,list) or len(binds)>128:raise RuntimeSpecError("invalid bind_paths")
 result["bind_paths"]=[{"source":_absolute(x.get("source"),"bind source"),"target":_absolute(x.get("target"),"bind target")} for x in binds if isinstance(x,dict)]
 if len(result["bind_paths"])!=len(binds):raise RuntimeSpecError("invalid bind_paths")
 result["path"]=result["working_directory"];return result
__all__=["RuntimeSpecError","VALID_DESIRED_STATES","validate_runtime_spec"]
