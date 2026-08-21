#!/usr/bin/env python3
"""Canonical contracts for Capivara automation and universal broadcast."""
from __future__ import annotations
import hashlib,json,re
from typing import Any,Mapping
_TOKEN=re.compile(r"^[A-Za-z0-9._:-]{1,191}$")
_TRIGGER_TYPES={"event","schedule","manual","metric"}
_ACTION_TYPES={"broadcast","backup","instance","content","configuration"}
_BROADCAST_SCOPES={"instance","agent","game","customer","region","datacenter","global"}
class AutomationValidationError(ValueError):pass
def _json(value:Any)->str:return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def _token(value:Any,label:str)->str:
 s=str(value or "").strip()
 if not _TOKEN.fullmatch(s):raise AutomationValidationError(f"invalid {label}")
 return s
def normalize_broadcast(raw:Mapping[str,Any])->dict[str,Any]:
 if not isinstance(raw,Mapping):raise AutomationValidationError("broadcast must be an object")
 scope=str(raw.get("scope") or "instance").strip().lower()
 if scope not in _BROADCAST_SCOPES:raise AutomationValidationError("invalid broadcast scope")
 message=str(raw.get("message") or "").strip()
 if not message or len(message)>4000:raise AutomationValidationError("invalid broadcast message")
 target=str(raw.get("target") or "").strip()
 if scope!="global":target=_token(target,"broadcast target")
 ttl=max(1,min(int(raw.get("ttl_seconds") or 300),86400));priority=str(raw.get("priority") or "normal").lower()
 if priority not in {"low","normal","high","critical"}:raise AutomationValidationError("invalid broadcast priority")
 return {"schema_version":1,"kind":"CapivaraBroadcast","scope":scope,"target":target or None,"message":message,"priority":priority,"ttl_seconds":ttl,"require_ack":bool(raw.get("require_ack",True))}
def normalize_rule(raw:Mapping[str,Any])->dict[str,Any]:
 if not isinstance(raw,Mapping):raise AutomationValidationError("automation rule must be an object")
 rule_id=_token(raw.get("rule_id"),"rule_id");name=str(raw.get("name") or rule_id).strip()[:191];enabled=bool(raw.get("enabled",True))
 trigger=dict(raw.get("trigger") or {});tt=str(trigger.get("type") or "").strip().lower()
 if tt not in _TRIGGER_TYPES:raise AutomationValidationError("invalid trigger type")
 if tt=="event":trigger["event_type"]=_token(trigger.get("event_type"),"event_type").upper()
 elif tt=="schedule":
  expr=str(trigger.get("expression") or "").strip()
  if not expr or len(expr)>191:raise AutomationValidationError("invalid schedule expression")
  trigger["expression"]=expr
 elif tt=="metric":
  trigger["metric_name"]=_token(trigger.get("metric_name"),"metric_name");trigger["operator"]=str(trigger.get("operator") or ">=")
  if trigger["operator"] not in {">",">=","<","<=","==","!="}:raise AutomationValidationError("invalid metric operator")
  try:trigger["value"]=float(trigger.get("value"))
  except (TypeError,ValueError):raise AutomationValidationError("invalid metric threshold")
 actions=[]
 for raw_action in raw.get("actions") or []:
  if not isinstance(raw_action,Mapping):raise AutomationValidationError("action must be an object")
  action=dict(raw_action);atype=str(action.get("type") or "").strip().lower()
  if atype not in _ACTION_TYPES:raise AutomationValidationError("invalid action type")
  action["type"]=atype
  if atype=="broadcast":action["broadcast"]=normalize_broadcast(action.get("broadcast") or {})
  elif atype=="instance":
   operation=str(action.get("operation") or "").strip().lower()
   if operation not in {"start","stop","restart"}:raise AutomationValidationError("invalid instance operation")
   action["operation"]=operation;action["instance_id"]=_token(action.get("instance_id"),"instance_id")
  elif atype=="backup":action["instance_id"]=_token(action.get("instance_id"),"instance_id")
  actions.append(action)
 if not actions:raise AutomationValidationError("rule requires actions")
 identity={"rule_id":rule_id,"name":name,"enabled":enabled,"trigger":trigger,"conditions":list(raw.get("conditions") or []),"actions":actions,"cooldown_seconds":max(0,min(int(raw.get("cooldown_seconds") or 0),86400))}
 return {"schema_version":1,"kind":"CapivaraAutomationRule",**identity,"checksum":hashlib.sha256(_json(identity).encode()).hexdigest()}
__all__=["AutomationValidationError","normalize_rule","normalize_broadcast"]
