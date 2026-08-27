"""Windows Agent-owned storage pool policy for private per-instance state."""
from __future__ import annotations
import ntpath,re,shutil
from pathlib import Path
from typing import Any
import os

PROGRAM_DATA=Path(os.environ.get("PROGRAMDATA",r"C:\ProgramData"))
DEFAULT_INSTANCE_STORAGE_ROOT=PROGRAM_DATA/"CapivaraAgent"/"instances"
DEFAULT_STORAGE_POOL_ID="default"
_POOL_ID=re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_STORAGE_CLASS=re.compile(r"^[A-Za-z0-9._-]{1,64}$")

def _is_native_absolute(raw:str)->bool:return Path(raw).is_absolute()
def _is_windows_absolute(raw:str)->bool:return ntpath.isabs(raw)
def _absolute(raw:str)->bool:return _is_native_absolute(raw) or _is_windows_absolute(raw)
def _norm(raw:str)->str:
 if _is_native_absolute(raw):return str(Path(raw).resolve(strict=False))
 if _is_windows_absolute(raw):return ntpath.normpath(raw)
 raise ValueError("path must be absolute")
def _case(value:str)->str:
 if _is_native_absolute(value):return os.path.normcase(str(Path(value).resolve(strict=False)))
 return ntpath.normcase(ntpath.normpath(value))
def _child_of(target:str,base:str)->bool:
 if _is_native_absolute(target) and _is_native_absolute(base):
  try:Path(target).resolve(strict=False).relative_to(Path(base).resolve(strict=False));return True
  except ValueError:return False
 t=ntpath.normcase(ntpath.normpath(target));b=ntpath.normcase(ntpath.normpath(base));return t==b or t.startswith(b.rstrip("\\/")+"\\")
def _root(value:Any,label:str="storage pool root")->str:
 raw=str(value or "").strip()
 if not raw or not _absolute(raw):raise ValueError(f"{label} must be an absolute path")
 normalized=_norm(raw)
 if _is_native_absolute(normalized) and Path(normalized).parent==Path(normalized):raise ValueError(f"{label} cannot be filesystem root")
 if _is_windows_absolute(normalized):
  drive,tail=ntpath.splitdrive(normalized)
  if drive and tail in {"\\","/"}:raise ValueError(f"{label} cannot be filesystem root")
 protected=[os.environ.get("WINDIR",r"C:\Windows"),os.environ.get("ProgramFiles",r"C:\Program Files"),os.environ.get("ProgramFiles(x86)",r"C:\Program Files (x86)")]
 for item in protected:
  if item and _child_of(normalized,str(item)):raise ValueError(f"{label} is inside a protected system path")
 return normalized
def _pool_id(value:Any)->str:
 token=str(value or "").strip()
 if not _POOL_ID.fullmatch(token):raise ValueError("invalid storage_pool_id")
 return token
def _storage_class(value:Any)->str:
 token=str(value or "standard").strip().lower()
 if not _STORAGE_CLASS.fullmatch(token):raise ValueError("invalid storage_class")
 return token
def _normalize_pool(raw:dict[str,Any])->dict[str,Any]:
 pool_id=_pool_id(raw.get("id") or raw.get("storage_pool_id"));reserve=int(raw.get("reserve_bytes") or 0);priority=int(raw.get("priority") or 0)
 if reserve<0:raise ValueError("storage pool reserve_bytes cannot be negative")
 return {"id":pool_id,"name":str(raw.get("name") or pool_id).strip()[:160] or pool_id,"root_path":_root(raw.get("root_path") or raw.get("root"),f"storage pool {pool_id} root"),"storage_class":_storage_class(raw.get("storage_class")),"enabled":bool(raw.get("enabled",True)),"priority":priority,"reserve_bytes":reserve}
def storage_pools(config:dict[str,Any])->list[dict[str,Any]]:
 raw_pools=config.get("storage_pools") if isinstance(config,dict) else None
 if not isinstance(raw_pools,list) or not raw_pools:
  root=_root((config or {}).get("instance_storage_root") or DEFAULT_INSTANCE_STORAGE_ROOT,"Agent instance_storage_root")
  return [{"id":DEFAULT_STORAGE_POOL_ID,"name":"Default","root_path":root,"storage_class":"standard","enabled":True,"priority":0,"reserve_bytes":0,"legacy":True}]
 pools=[];ids=set();roots=set()
 for item in raw_pools:
  if not isinstance(item,dict):raise ValueError("storage_pools entries must be objects")
  pool=_normalize_pool(item);root_key=_case(pool["root_path"])
  if pool["id"] in ids:raise ValueError(f"duplicate storage pool id: {pool['id']}")
  if root_key in roots:raise ValueError(f"duplicate storage pool root: {pool['root_path']}")
  ids.add(pool["id"]);roots.add(root_key);pools.append(pool)
 return pools
def default_storage_pool_id(config:dict[str,Any])->str:
 pools=storage_pools(config)
 if len(pools)==1 and pools[0].get("legacy"):return DEFAULT_STORAGE_POOL_ID
 requested=str((config or {}).get("default_storage_pool_id") or "").strip()
 if not requested:
  enabled=[pool for pool in pools if pool["enabled"]]
  if len(enabled)==1:return str(enabled[0]["id"])
  raise ValueError("default_storage_pool_id is required when multiple storage pools are configured")
 requested=_pool_id(requested)
 if requested not in {pool["id"] for pool in pools}:raise ValueError("default_storage_pool_id does not exist")
 return requested
def resolve_storage_pool(config:dict[str,Any],pool_id:str|None=None,*,require_enabled:bool=True)->dict[str,Any]:
 selected=_pool_id(pool_id) if pool_id else default_storage_pool_id(config)
 for pool in storage_pools(config):
  if pool["id"]==selected:
   if require_enabled and not pool["enabled"]:raise ValueError(f"storage pool is disabled: {selected}")
   return dict(pool)
 raise ValueError(f"storage pool not found: {selected}")
def instance_storage_root(config:dict[str,Any],pool_id:str|None=None)->Path:return Path(resolve_storage_pool(config,pool_id)["root_path"])
def pool_inventory(config:dict[str,Any])->list[dict[str,Any]]:
 result=[];default_id=default_storage_pool_id(config)
 for pool in storage_pools(config):
  item=dict(pool);item["default"]=pool["id"]==default_id
  try:usage=shutil.disk_usage(pool["root_path"])
  except OSError as exc:item.update({"health":"unavailable","error":str(exc)[:500],"total_bytes":None,"free_bytes":None,"usable_bytes":None})
  else:item.update({"health":"online","total_bytes":int(usage.total),"free_bytes":int(usage.free),"usable_bytes":max(0,int(usage.free)-int(pool["reserve_bytes"]))})
  result.append(item)
 return result
__all__=["DEFAULT_INSTANCE_STORAGE_ROOT","DEFAULT_STORAGE_POOL_ID","default_storage_pool_id","instance_storage_root","pool_inventory","resolve_storage_pool","storage_pools"]
