#!/usr/bin/env python3
"""Transport-neutral Agent inventory/heartbeat service boundary."""
from __future__ import annotations
import re
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
def _metric_token(value:Any)->str:
 text=re.sub(r"[^a-z0-9.]+",".",str(value or "").strip().lower().replace("_","."));return text.strip(".") or "unknown"
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
 return result[:2000]
def record_agent_heartbeat(authenticated_agent_id:str,payload:dict[str,Any]|None,*,backend)->dict[str,Any]:
 agent_id=str(authenticated_agent_id or "").strip()
 if not agent_id:raise PermissionError("authenticated Agent identity required")
 body=payload if isinstance(payload,dict) else {};claimed=str(body.get("agent_id") or agent_id).strip()
 if claimed!=agent_id:raise PermissionError("Agent identity mismatch")
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
