"""Validated Windows Agent-local instance runtime specification."""
from __future__ import annotations
import os,re
from pathlib import Path
from typing import Any
_TOKEN=re.compile(r"^[A-Za-z0-9._-]{1,191}$");VALID_DESIRED_STATES={"running","stopped"}
class RuntimeSpecError(ValueError):pass
def _token(v,label):
 t=str(v or "").strip()
 if not _TOKEN.fullmatch(t):raise RuntimeSpecError(f"invalid {label}")
 return t
def _absolute(v,label):
 t=str(v or "").strip()
 if not t or not os.path.isabs(t) or "\n" in t or "\r" in t:raise RuntimeSpecError(f"invalid {label}")
 return str(Path(t))
def validate_runtime_spec(spec:dict[str,Any],*,expected_agent_id:str|None=None)->dict[str,Any]:
 if not isinstance(spec,dict):raise RuntimeSpecError("runtime spec must be an object")
 r=dict(spec);r["schema_version"]=1;r["kind"]="CapivaraInstanceRuntimeSpec";r["instance_id"]=_token(r.get("instance_id"),"instance_id");r["agent_id"]=_token(r.get("agent_id"),"agent_id")
 if expected_agent_id is not None and r["agent_id"]!=_token(expected_agent_id,"expected_agent_id"):raise RuntimeSpecError("runtime spec belongs to another Agent")
 r["runtime_id"]=_token(r.get("runtime_id") or r["instance_id"],"runtime_id");r["adapter"]=_token(r.get("adapter") or "windows-process","adapter").lower()
 if r["adapter"] not in {"windows-process","windows-service"}:raise RuntimeSpecError("unsupported runtime materialization adapter")
 r["working_directory"]=_absolute(r.get("working_directory") or r.get("path"),"working_directory")
 if r["adapter"]=="windows-process":r["executable"]=_absolute(r.get("executable"),"executable")
 args=r.get("arguments",[])
 if not isinstance(args,list) or len(args)>128:raise RuntimeSpecError("invalid arguments")
 out=[]
 for item in args:
  v=str(item)
  if "\x00" in v or "\n" in v or "\r" in v or len(v)>4096:raise RuntimeSpecError("invalid runtime argument")
  out.append(v)
 r["arguments"]=out;env=r.get("environment",{})
 if not isinstance(env,dict) or len(env)>128:raise RuntimeSpecError("invalid environment")
 normalized={}
 for k,v in env.items():
  name=str(k);text=str(v)
  if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}",name) or "\x00" in text or "\n" in text or "\r" in text:raise RuntimeSpecError("invalid environment entry")
  normalized[name]=text
 r["environment"]=normalized;desired=str(r.get("desired_state") or "stopped").lower()
 if desired not in VALID_DESIRED_STATES:raise RuntimeSpecError("invalid desired_state")
 r["desired_state"]=desired;r["path"]=r["working_directory"];return r
__all__=["RuntimeSpecError","VALID_DESIRED_STATES","validate_runtime_spec"]
