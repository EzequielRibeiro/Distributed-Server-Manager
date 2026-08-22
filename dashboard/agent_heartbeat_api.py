#!/usr/bin/env python3
"""Transport-neutral Agent inventory/heartbeat service boundary."""
from __future__ import annotations
import json,re
from typing import Any
from agent_instance_reconciliation_repository import AgentInstanceReconciliationRepository
from agent_instance_runtime_health_repository import AgentInstanceRuntimeHealthRepository
from agent_runtime_repository import AgentRuntimeRepository
from automation_repository import AutomationRepository
from backup_repository import BackupRepository
from configuration_repository import ConfigurationRepository
from content_repository import ContentRepository
from observability_repository import ObservabilityRepository
from universal_event_repository import UniversalEventRepository
from alert_repository import AlertSession,dialect_for_backend

def _metric_token(value:Any)->str:
 text=re.sub(r"[^a-z0-9.]+",".",str(value or "").strip().lower().replace("_","."));return text.strip(".") or "unknown"

def _numeric(value:Any)->float|None:
 if isinstance(value,(int,float)) and not isinstance(value,bool):return float(value)
 return None

def _append_metric(result:list[dict[str,Any]],name:str,value:Any,unit:str,*,scope_type:str="agent",instance_id:str|None=None,collected_at:Any=None,dimensions:dict[str,Any]|None=None):
 number=_numeric(value)
 if number is None:return
 sample={"metric_name":name,"metric_type":"gauge","value":number,"unit":unit,"scope_type":scope_type}
 if instance_id:sample["instance_id"]=instance_id
 if collected_at:sample["collected_at"]=collected_at
 if dimensions:sample["dimensions"]=dimensions
 result.append(sample)

def _resource_samples(body:dict[str,Any],result:list[dict[str,Any]])->None:
 host=body.get("host_telemetry")
 if isinstance(host,dict):
  at=host.get("collected_at");dims={"component":"host"};memory=host.get("memory") if isinstance(host.get("memory"),dict) else {};storage=host.get("storage") if isinstance(host.get("storage"),dict) else {};load=host.get("load") if isinstance(host.get("load"),dict) else {};network=host.get("network") if isinstance(host.get("network"),dict) else {}
  _append_metric(result,"host.cpu.percent",host.get("cpu_percent"),"percent",collected_at=at,dimensions=dims)
  _append_metric(result,"host.memory.used.percent",memory.get("used_percent"),"percent",collected_at=at,dimensions=dims)
  _append_metric(result,"host.memory.used.bytes",memory.get("used_bytes"),"bytes",collected_at=at,dimensions=dims)
  _append_metric(result,"host.memory.available.bytes",memory.get("available_bytes"),"bytes",collected_at=at,dimensions=dims)
  _append_metric(result,"host.storage.used.percent",storage.get("used_percent"),"percent",collected_at=at,dimensions=dims)
  _append_metric(result,"host.storage.free.bytes",storage.get("free_bytes"),"bytes",collected_at=at,dimensions=dims)
  _append_metric(result,"host.load.1",load.get("load1"),"load",collected_at=at,dimensions=dims)
  _append_metric(result,"host.load.5",load.get("load5"),"load",collected_at=at,dimensions=dims)
  _append_metric(result,"host.load.15",load.get("load15"),"load",collected_at=at,dimensions=dims)
  _append_metric(result,"host.uptime.seconds",host.get("uptime_seconds"),"seconds",collected_at=at,dimensions=dims)
  _append_metric(result,"host.network.rx.bytes",network.get("rx_bytes"),"bytes",collected_at=at,dimensions=dims)
  _append_metric(result,"host.network.tx.bytes",network.get("tx_bytes"),"bytes",collected_at=at,dimensions=dims)
 agent=body.get("agent_telemetry")
 if isinstance(agent,dict):
  at=agent.get("collected_at");dims={"component":"capivara-agent"}
  _append_metric(result,"agent.cpu.percent",agent.get("cpu_percent"),"percent",collected_at=at,dimensions=dims)
  _append_metric(result,"agent.memory.rss.bytes",agent.get("rss_bytes"),"bytes",collected_at=at,dimensions=dims)
  _append_metric(result,"agent.threads",agent.get("threads"),"threads",collected_at=at,dimensions=dims)
  _append_metric(result,"agent.pid",agent.get("pid"),"pid",collected_at=at,dimensions=dims)
 for item in body.get("instance_resource_metrics") or []:
  if not isinstance(item,dict):continue
  instance_id=str(item.get("instance_id") or "").strip()
  if not instance_id:continue
  at=item.get("collected_at");dims={"component":"instance","game_id":str(item.get("game_id") or ""),"observed_state":str(item.get("observed_state") or "unknown")}
  for name,key,unit in (("instance.cpu.percent","cpu_percent","percent"),("instance.memory.bytes","memory_bytes","bytes"),("instance.tasks","tasks","tasks"),("instance.io.read.bytes","io_read_bytes","bytes"),("instance.io.write.bytes","io_write_bytes","bytes"),("instance.pid","pid","pid")):
   _append_metric(result,name,item.get(key),unit,scope_type="instance",instance_id=instance_id,collected_at=at,dimensions=dims)

def _observability_from_heartbeat(agent_id:str,body:dict[str,Any])->list[dict[str,Any]]:
 result=[];runtime=body.get("instance_runtime_metrics")
 if isinstance(runtime,dict):
  for item in runtime.get("observability_samples") or []:
   if isinstance(item,dict):value=dict(item);value.pop("agent_id",None);result.append(value)
  for name,value in (runtime.get("counters") or {}).items():
   if isinstance(value,(int,float)) and not isinstance(value,bool):result.append({"metric_name":"capivara.runtime.counter."+_metric_token(name),"metric_type":"counter","value":value,"unit":"1","scope_type":"agent"})
  for name,value in (runtime.get("queue_depth") or {}).items():
   if isinstance(value,(int,float)) and not isinstance(value,bool):result.append({"metric_name":"capivara.runtime.queue."+_metric_token(name),"metric_type":"gauge","value":value,"unit":"items","scope_type":"agent"})
  for name,stats in (runtime.get("durations_ms") or {}).items():
   if not isinstance(stats,dict):continue
   for field in ("count","total","max"):
    value=stats.get(field)
    if isinstance(value,(int,float)) and not isinstance(value,bool):result.append({"metric_name":f"capivara.runtime.duration.{_metric_token(name)}.{field}","metric_type":"counter" if field in {"count","total"} else "gauge","value":value,"unit":"1" if field=="count" else "milliseconds","scope_type":"agent"})
 health_map={"healthy":1.0,"transitioning":.5,"unknown":-1.0,"degraded":0.0}
 for item in body.get("instance_runtime_health") or []:
  if not isinstance(item,dict) or not item.get("instance_id"):continue
  health=str(item.get("health") or "unknown").lower();result.append({"metric_name":"instance.health","metric_type":"gauge","scope_type":"instance","instance_id":str(item["instance_id"]),"value":health_map.get(health,-1.0),"unit":"state","collected_at":item.get("generated_at"),"dimensions":{"health":health,"desired_state":str(item.get("desired_state") or "unknown"),"observed_state":str(item.get("observed_state") or "unknown")}})
 _resource_samples(body,result)
 return result[:2000]

def record_agent_heartbeat(authenticated_agent_id:str,payload:dict[str,Any]|None,*,backend)->dict[str,Any]:
 agent_id=str(authenticated_agent_id or "").strip()
 if not agent_id:raise PermissionError("authenticated Agent identity required")
 body=payload if isinstance(payload,dict) else {};claimed=str(body.get("agent_id") or agent_id).strip()
 if claimed!=agent_id:raise PermissionError("Agent identity mismatch")
 logs=body.get("agent_logs")
 if isinstance(logs,list):
  safe_logs=[str(line).replace("\x00","")[:2000] for line in logs[-200:] if isinstance(line,str)]
  dialect=dialect_for_backend(backend);ph=dialect.placeholder
  with backend.transaction() as connection:
   session=AlertSession(backend,connection)
   try:
    row=session.execute(f"SELECT metadata_json FROM agents WHERE id={ph}",(agent_id,)).fetchone();metadata=json.loads(str(row["metadata_json"] or "{}")) if row else {};metadata["recent_logs"]=safe_logs;session.execute(f"UPDATE agents SET metadata_json={ph} WHERE id={ph}",(json.dumps(metadata,separators=(",",":")),agent_id))
   finally:session.close()
 repository=AgentRuntimeRepository(backend);repository.initialize();inventory_fields={"hostname":body.get("hostname"),"os_name":body.get("os") or body.get("os_name"),"architecture":body.get("architecture"),"capivara_version":body.get("capivara_version"),"address":body.get("address"),"fingerprint":body.get("fingerprint"),"capabilities":body.get("capabilities"),"cpu":body.get("cpu"),"ram_total_bytes":body.get("ram_total_bytes"),"storage":body.get("storage"),"network":body.get("network"),"heartbeat_interval_seconds":int(body.get("heartbeat_interval_seconds",30)),"degraded_after_seconds":int(body.get("degraded_after_seconds",60)),"offline_after_seconds":int(body.get("offline_after_seconds",120))}
 if any(inventory_fields[n] is not None for n in ("hostname","os_name","architecture","capivara_version","address","fingerprint","capabilities","cpu","ram_total_bytes","storage","network")):repository.upsert_inventory(agent_id=agent_id,**inventory_fields)
 reconciliation=body.get("instance_reconciliation")
 if isinstance(reconciliation,list):p=AgentInstanceReconciliationRepository(backend);p.initialize();p.apply_inventory(agent_id,reconciliation)
 runtime_health=body.get("instance_runtime_health")
 if isinstance(runtime_health,list):h=AgentInstanceRuntimeHealthRepository(backend);h.initialize();h.apply_inventory(agent_id,runtime_health)
 event_result={"accepted_event_ids":[],"accepted":0,"created":0,"rejected":0};runtime_events=body.get("runtime_events")
 if isinstance(runtime_events,list):events=UniversalEventRepository(backend);events.initialize();event_result=events.ingest_agent_events(agent_id,runtime_events)
 metrics=ObservabilityRepository(backend);metrics.initialize();metric_result=metrics.ingest_agent_samples(agent_id,_observability_from_heartbeat(agent_id,body))
 configurations=ConfigurationRepository(backend);configurations.initialize();configuration_state=body.get("configuration_state")
 if isinstance(configuration_state,list):configurations.record_agent_state(agent_id,configuration_state)
 desired_configuration=configurations.desired_for_agent(agent_id)
 contents=ContentRepository(backend);contents.initialize();reported_content=body.get("content_state")
 if isinstance(reported_content,list):contents.record_agent_state(agent_id,reported_content)
 desired_content=contents.desired_for_agent(agent_id)
 backups=BackupRepository(backend);backups.initialize();reported_backups=body.get("backup_state")
 if isinstance(reported_backups,list):backups.record_agent_state(agent_id,reported_backups)
 backup_commands=backups.commands_for_agent(agent_id)
 automations=AutomationRepository(backend);automations.initialize();reported_broadcasts=body.get("broadcast_state")
 if isinstance(reported_broadcasts,list):automations.record_broadcast_state(agent_id,reported_broadcasts)
 broadcast_commands=automations.desired_for_agent(agent_id)
 for command in broadcast_commands:command["agent_id"]=agent_id
 last_seen=repository.heartbeat(agent_id)
 return {"agent_id":agent_id,"health_status":"online","last_seen":last_seen,"accepted_event_ids":event_result["accepted_event_ids"],"events_accepted":event_result["accepted"],"events_created":event_result["created"],"events_rejected":event_result["rejected"],"metrics_accepted":metric_result["accepted"],"metrics_created":metric_result["created"],"metrics_rejected":metric_result["rejected"],"configuration_commands":desired_configuration,"configuration_count":len(desired_configuration),"content_commands":desired_content,"content_count":len(desired_content),"backup_commands":backup_commands,"backup_count":len(backup_commands),"broadcast_commands":broadcast_commands,"broadcast_count":len(broadcast_commands)}
