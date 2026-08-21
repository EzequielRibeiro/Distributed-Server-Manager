#!/usr/bin/env python3
"""HTTP transport adapter for D1 automation and broadcast."""
from __future__ import annotations
from urllib.parse import parse_qs
from automation_api import fire_event,fire_rule,list_broadcasts,list_rules,send_broadcast,set_rule
AUTOMATION_PATH="/api/automation";BROADCAST_PATH="/api/broadcasts"
def dispatch_automation_get(path,query,*,user,backend):
 try:
  q=parse_qs(query or "")
  if path==AUTOMATION_PATH:return 200,list_rules(user=user,backend=backend)
  if path==BROADCAST_PATH:return 200,list_broadcasts(user=user,backend=backend,limit=int((q.get("limit") or [200])[0]))
  return 404,{"error":"not_found"}
 except PermissionError as exc:return 403,{"error":"forbidden","message":str(exc)}
 except Exception as exc:return 400,{"error":"invalid_request","message":str(exc)}
def dispatch_automation_post(path,payload,*,user,backend):
 try:
  body=dict(payload or {})
  if path==BROADCAST_PATH:return 201,send_broadcast(body,user=user,backend=backend)
  if path!=AUTOMATION_PATH:return 404,{"error":"not_found"}
  action=str(body.pop("operation",body.pop("op","rule-set"))).lower()
  if action=="rule-set":return 200,set_rule(body,user=user,backend=backend)
  if action=="fire":return 200,fire_rule(body,user=user,backend=backend)
  if action=="event":return 200,fire_event(body,user=user,backend=backend)
  return 400,{"error":"invalid_operation","message":"unsupported automation operation"}
 except PermissionError as exc:return 403,{"error":"forbidden","message":str(exc)}
 except LookupError as exc:return 404,{"error":"not_found","message":str(exc)}
 except Exception as exc:return 400,{"error":"invalid_request","message":str(exc)}
__all__=["AUTOMATION_PATH","BROADCAST_PATH","dispatch_automation_get","dispatch_automation_post"]
