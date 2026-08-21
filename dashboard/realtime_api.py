#!/usr/bin/env python3
"""Stable v1 REST service boundary for external Capivara integrations."""
from __future__ import annotations
from typing import Any
from api_platform import has_scope
from automation_repository import AutomationRepository
from realtime_repository import RealtimeRepository
from universal_event_repository import UniversalEventRepository

def _require(principal,scope):
 if not isinstance(principal,dict) or not has_scope(principal,scope):raise PermissionError(f"API scope required: {scope}")
 return principal

def api_status(*,principal,backend):
 _require(principal,"realtime:read");r=RealtimeRepository(backend);r.initialize();return r.status()
def api_events(*,principal,backend,**filters):
 _require(principal,"events:read");r=RealtimeRepository(backend);r.initialize();return r.events(**filters)
def api_observability(*,principal,backend,**filters):
 _require(principal,"observability:read");r=RealtimeRepository(backend);r.initialize();return r.latest_observability(**filters)
def api_instances(*,principal,backend,**filters):
 _require(principal,"instances:read");r=RealtimeRepository(backend);r.initialize();return r.instances(**filters)
def api_broadcast(payload:dict[str,Any]|None,*,principal,backend):
 actor=_require(principal,"broadcasts:write");r=AutomationRepository(backend);r.initialize();result=r.create_broadcast(dict(payload or {}),requested_by="api:"+str(actor.get("token_id") or "unknown"));e=UniversalEventRepository(backend);e.initialize();e.publish({"event_type":"BROADCAST_REQUESTED","source":"api.v1.broadcast","severity":"info","actor_type":"api_token","actor_id":actor.get("token_id"),"data":{"broadcast_id":result["broadcast_id"],"scope":result["scope"],"target":result.get("target"),"recipients":result["recipients"]}});return result

def api_fire_automation(payload:dict[str,Any]|None,*,principal,backend):
 from automation_engine import AutomationEngine
 actor=_require(principal,"automation:write");body=dict(payload or {});return AutomationEngine(backend).fire_rule(str(body.get("rule_id") or ""),context=body.get("context") or {},requested_by="api:"+str(actor.get("token_id") or "unknown"))

__all__=["api_broadcast","api_events","api_fire_automation","api_instances","api_observability","api_status"]
