#!/usr/bin/env python3
"""Customer-scoped scheduled maintenance policy facade."""
from __future__ import annotations
from pathlib import Path
from typing import Any,Mapping
from core.maintenance_platform import normalize_capabilities,normalize_policy
from customer_instance_workspace_service import CustomerInstanceWorkspaceService
from maintenance_repository import MaintenanceRepository
from runtime_workspace_catalog import runtime_workspace_capabilities

_POLICY_FIELDS=frozenset({"enabled","schedule_mode","timezone","weekdays","start_time","interval_seconds","warning_offsets_seconds","warning_template","broadcast_enabled","coalesce_updates"})


def _run_view(run:Mapping[str,Any])->dict[str,Any]:
 event=run.get("event") if isinstance(run.get("event"),Mapping) else {}
 pending=[]
 for item in event.get("pending_work") or []:
  if not isinstance(item,Mapping):continue
  pending.append({key:item.get(key) for key in ("kind","ref","available_version","desired_revision","status","error") if item.get(key) is not None})
 return {key:run.get(key) for key in ("run_id","due_at","status","stage","error_code","error_detail","created_at","started_at","completed_at")}|{"warnings_sent":list(run.get("warnings_sent") or []),"pending_work":pending}


class CustomerMaintenanceWorkspaceService:
 def __init__(self,backend,root:Path):
  self.backend=backend;self.root=Path(root);self.workspace=CustomerInstanceWorkspaceService(backend,self.root);self.maintenance=MaintenanceRepository(backend);self.maintenance.initialize()
 def _context_capabilities(self,user,instance_id:str,permission:str="instance.view"):
  context=self.workspace.require(user,instance_id,permission);game=str(context.get("game_id") or "").strip();runtime=str(context.get("runtime_id") or "").strip();raw=(runtime_workspace_capabilities(self.root,game,runtime).get("maintenance") or {}) if game and runtime else {};return context,normalize_capabilities(raw)
 def _editable(self,user,instance_id:str)->bool:
  permissions=self.workspace.permissions(user,instance_id);return "instance.restart" in permissions and "settings.write" in permissions
 def view(self,user,instance_id:str)->dict[str,Any]:
  _,caps=self._context_capabilities(user,instance_id,"instance.view")
  configured=True
  try:snapshot=self.maintenance.snapshot(instance_id)
  except KeyError:
   configured=False;snapshot={"policy":normalize_policy({}),"state":None,"runs":[]}
  policy=normalize_policy(snapshot.get("policy") if isinstance(snapshot.get("policy"),Mapping) else {})
  state=snapshot.get("state") if isinstance(snapshot.get("state"),Mapping) else {}
  return {"instance_id":str(instance_id),"configured":configured,"editable":self._editable(user,instance_id),"policy":policy,"capabilities":caps,"state":{"next_due_at":state.get("next_due_at"),"last_started_at":state.get("last_started_at"),"last_completed_at":state.get("last_completed_at"),"last_error":state.get("last_error"),"active":bool(state.get("active_run_id"))},"runs":[_run_view(run) for run in (snapshot.get("runs") or [])[:10] if isinstance(run,Mapping)]}
 def save(self,user,instance_id:str,body:Mapping[str,Any]|None)->dict[str,Any]:
  self.workspace.require(user,instance_id,"instance.restart");self.workspace.require(user,instance_id,"settings.write");_,caps=self._context_capabilities(user,instance_id,"instance.view")
  if not isinstance(body,Mapping):raise ValueError("maintenance policy must be an object")
  unknown=sorted(set(body)-_POLICY_FIELDS-{"instance_id"})
  if unknown:raise ValueError("unsupported maintenance policy fields: "+", ".join(unknown))
  payload={key:body[key] for key in _POLICY_FIELDS if key in body};policy=normalize_policy(payload)
  if policy["enabled"] and not caps["scheduled_restart"]:raise PermissionError("scheduled restart is unavailable for this runtime")
  if policy["broadcast_enabled"] and not (caps["broadcast"] or caps["native_countdown"]):policy["broadcast_enabled"]=False
  actor=str((user or {}).get("username") or (user or {}).get("id") or "customer")
  self.maintenance.set_policy(instance_id,policy,requested_by=actor);return self.view(user,instance_id)


__all__=["CustomerMaintenanceWorkspaceService"]
