#!/usr/bin/env python3
"""Administrative service boundary for D1 automation and universal broadcast."""
from __future__ import annotations
from typing import Any
from automation_engine import AutomationEngine
from automation_repository import AutomationRepository
from universal_event_repository import UniversalEventRepository
def _admin(user):
 actor=user if isinstance(user,dict) else {}
 if str(actor.get("role") or "").lower() not in {"admin","controller"}:raise PermissionError("administrator access required")
 return actor
def list_rules(*,user,backend):
 _admin(user);r=AutomationRepository(backend);r.initialize();rows=r.list_rules();return {"schema_version":1,"kind":"CapivaraAutomationRuleList","rules":rows,"count":len(rows)}
def list_broadcasts(*,user,backend,limit=200):
 _admin(user);r=AutomationRepository(backend);r.initialize();rows=r.list_broadcasts(limit);return {"schema_version":1,"kind":"CapivaraBroadcastList","broadcasts":rows,"count":len(rows)}
def set_rule(payload:dict[str,Any]|None,*,user,backend):
 actor=_admin(user);who=str(actor.get("username") or actor.get("id") or "admin");r=AutomationRepository(backend);r.initialize();result=r.put_rule(dict(payload or {}),requested_by=who)
 if result["changed"]:
  rule=result["rule"];e=UniversalEventRepository(backend);e.initialize();e.publish({"event_type":"AUTOMATION_RULE_UPDATED","source":"controller.automation","severity":"info","actor_type":"dashboard_user","actor_id":who,"data":{"rule_id":rule["rule_id"],"revision":rule["revision"],"enabled":rule["enabled"],"trigger":rule["trigger"]}})
 return result
def send_broadcast(payload:dict[str,Any]|None,*,user,backend):
 actor=_admin(user);who=str(actor.get("username") or actor.get("id") or "admin");r=AutomationRepository(backend);r.initialize();result=r.create_broadcast(dict(payload or {}),requested_by=who);e=UniversalEventRepository(backend);e.initialize();e.publish({"event_type":"BROADCAST_REQUESTED","source":"controller.broadcast","severity":"info","actor_type":"dashboard_user","actor_id":who,"data":{"broadcast_id":result["broadcast_id"],"scope":result["scope"],"target":result.get("target"),"priority":result["priority"],"recipients":result["recipients"]}});return result
def fire_rule(payload:dict[str,Any]|None,*,user,backend):
 actor=_admin(user);body=dict(payload or {});who=str(actor.get("username") or actor.get("id") or "admin");return AutomationEngine(backend).fire_rule(str(body.get("rule_id") or ""),context=body.get("context") or {},requested_by=who)
def fire_event(payload:dict[str,Any]|None,*,user,backend):
 actor=_admin(user);body=dict(payload or {});who=str(actor.get("username") or actor.get("id") or "admin");context=dict(body.get("context") or {});context["event_type"]=str(body.get("event_type") or "");return AutomationEngine(backend).fire("event",context,trigger_ref=body.get("event_id"),requested_by=who)
__all__=["list_rules","list_broadcasts","set_rule","send_broadcast","fire_rule","fire_event"]
