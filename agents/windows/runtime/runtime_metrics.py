"""Durable runtime metrics producer for Windows Agent observability."""
from __future__ import annotations
import json,os
from pathlib import Path
from typing import Any
import instance_runtime
from queue_observability import collect_queue_observability
from storage_pools import pool_inventory

def _path():return Path(instance_runtime.STATE_DIR)/"metrics"/"instance-runtime.json"
def _agent_config()->dict[str,Any]:
 program_data=Path(os.environ.get("PROGRAMDATA",r"C:\ProgramData"));path=Path(os.environ.get("CAPIVARA_AGENT_CONFIG",program_data/"CapivaraAgent"/"agent.json"))
 try:value=json.loads(path.read_text(encoding="utf-8"))
 except (OSError,ValueError):return {}
 return value if isinstance(value,dict) else {}
def _read()->dict[str,Any]:
 try:v=json.loads(_path().read_text(encoding="utf-8"))
 except (OSError,ValueError):return {"schema_version":1,"kind":"CapivaraInstanceRuntimeMetrics","counters":{},"durations_ms":{}}
 return v if isinstance(v,dict) else {"schema_version":1,"kind":"CapivaraInstanceRuntimeMetrics","counters":{},"durations_ms":{}}
def _write(payload):
 p=_path();p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(f".{p.name}.{os.getpid()}.tmp");tmp.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8");os.replace(tmp,p)
def increment(name:str,amount:int=1):
 payload=_read();c=payload.setdefault("counters",{});c[name]=int(c.get(name,0))+int(amount);_write(payload)
def observe_duration(name:str,duration_ms:int):
 payload=_read();d=payload.setdefault("durations_ms",{});item=d.setdefault(name,{"count":0,"total":0,"max":0});v=max(0,int(duration_ms));item["count"]=int(item.get("count",0))+1;item["total"]=int(item.get("total",0))+v;item["max"]=max(int(item.get("max",0)),v);_write(payload)
def _storage_pool_samples(pools:list[dict[str,Any]])->list[dict[str,Any]]:
 samples=[]
 for pool in pools:
  dims={"storage_pool_id":str(pool.get("id") or "unknown"),"storage_class":str(pool.get("storage_class") or "standard"),"health":str(pool.get("health") or "unknown"),"enabled":str(bool(pool.get("enabled",True))).lower(),"default":str(bool(pool.get("default",False))).lower()}
  for field in ("total_bytes","free_bytes","usable_bytes","reserve_bytes"):
   value=pool.get(field)
   if isinstance(value,(int,float)) and not isinstance(value,bool):samples.append({"metric_name":f"capivara.storage.pool.{field}","metric_type":"gauge","value":value,"unit":"bytes","scope_type":"agent","dimensions":dims})
  priority=pool.get("priority")
  if isinstance(priority,(int,float)) and not isinstance(priority,bool):samples.append({"metric_name":"capivara.storage.pool.priority","metric_type":"gauge","value":priority,"unit":"1","scope_type":"agent","dimensions":dims})
  samples.append({"metric_name":"capivara.storage.pool.health","metric_type":"gauge","value":1 if pool.get("health")=="online" else 0,"unit":"state","scope_type":"agent","dimensions":dims})
 return samples
def snapshot(*,queue_depth:dict[str,int]|None=None)->dict[str,Any]:
 payload=_read()
 if queue_depth is not None:payload["queue_depth"]={str(k):max(0,int(v)) for k,v in queue_depth.items()}
 config=_agent_config();stale_after=max(30,int(config.get("queue_stale_after_seconds",300) or 300));payload["queue_health"]=collect_queue_observability(Path(instance_runtime.STATE_DIR),stale_after_seconds=stale_after);payload["queue_stale_count"]=sum(1 for item in payload["queue_health"].values() if item.get("stale"));pools=[]
 if config:
  try:pools=pool_inventory(config)
  except (OSError,ValueError):pools=[]
 payload["storage_pools"]=pools;payload["observability_samples"]=_storage_pool_samples(pools);payload["telemetry"]={"storage_pools":pools} if pools else {}
 return payload
__all__=["increment","observe_duration","snapshot"]
