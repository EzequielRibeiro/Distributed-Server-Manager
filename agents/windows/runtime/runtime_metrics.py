"""Durable runtime metrics producer for Windows Agent observability."""
from __future__ import annotations
import json,os
from pathlib import Path
from typing import Any
import instance_runtime
def _path():return Path(instance_runtime.STATE_DIR)/"metrics"/"instance-runtime.json"
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
def snapshot(*,queue_depth:dict[str,int]|None=None)->dict[str,Any]:
 payload=_read()
 if queue_depth is not None:payload["queue_depth"]={str(k):max(0,int(v)) for k,v in queue_depth.items()}
 return payload
__all__=["increment","observe_duration","snapshot"]
