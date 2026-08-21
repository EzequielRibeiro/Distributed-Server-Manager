#!/usr/bin/env python3
"""HTTP transport for the versioned D2 REST and Server-Sent Events API."""
from __future__ import annotations
import json
import time
from urllib.parse import parse_qs
from api_platform import ApiValidationError,has_scope
from realtime_api import api_broadcast,api_events,api_fire_automation,api_instances,api_observability,api_status
from realtime_repository import RealtimeRepository

API_STATUS_PATH="/api/v1/status"
API_EVENTS_PATH="/api/v1/events"
API_OBSERVABILITY_PATH="/api/v1/observability/latest"
API_INSTANCES_PATH="/api/v1/instances"
API_BROADCAST_PATH="/api/v1/broadcasts"
API_AUTOMATION_PATH="/api/v1/automation/fire"
SSE_EVENTS_PATH="/api/v1/stream/events"
PUBLIC_GET_PATHS={API_STATUS_PATH,API_EVENTS_PATH,API_OBSERVABILITY_PATH,API_INSTANCES_PATH}
PUBLIC_POST_PATHS={API_BROADCAST_PATH,API_AUTOMATION_PATH}

def _first(q,key,default=None):return (q.get(key) or [default])[0]
def _limit(q,default=100):
 try:return max(1,min(int(_first(q,"limit",default)),500))
 except Exception:return default

def dispatch_realtime_get(path,query,*,principal,backend):
 q=parse_qs(query or "")
 try:
  if path==API_STATUS_PATH:return 200,api_status(principal=principal,backend=backend)
  if path==API_EVENTS_PATH:return 200,api_events(principal=principal,backend=backend,cursor=_first(q,"cursor"),limit=_limit(q),event_type=_first(q,"event_type"),agent_id=_first(q,"agent_id"),instance_id=_first(q,"instance_id"),severity=_first(q,"severity"))
  if path==API_OBSERVABILITY_PATH:return 200,api_observability(principal=principal,backend=backend,agent_id=_first(q,"agent_id"),instance_id=_first(q,"instance_id"),metric_name=_first(q,"metric_name"),limit=_limit(q,500))
  if path==API_INSTANCES_PATH:return 200,api_instances(principal=principal,backend=backend,agent_id=_first(q,"agent_id"),customer_id=_first(q,"customer_id"),game_id=_first(q,"game_id"),limit=_limit(q,500))
  return 404,{"error":"not_found"}
 except PermissionError as exc:return 403,{"error":"forbidden","message":str(exc)}
 except (ApiValidationError,ValueError) as exc:return 400,{"error":"invalid_request","message":str(exc)}

def dispatch_realtime_post(path,payload,*,principal,backend):
 try:
  if path==API_BROADCAST_PATH:return 202,api_broadcast(payload,principal=principal,backend=backend)
  if path==API_AUTOMATION_PATH:return 202,api_fire_automation(payload,principal=principal,backend=backend)
  return 404,{"error":"not_found"}
 except PermissionError as exc:return 403,{"error":"forbidden","message":str(exc)}
 except (ApiValidationError,ValueError,LookupError) as exc:return 400,{"error":"invalid_request","message":str(exc)}

def serve_event_stream(handler,query,*,principal,backend):
 if not has_scope(principal,"realtime:read") or not has_scope(principal,"events:read"):
  handler.send_json(403,{"error":"forbidden","message":"API scopes realtime:read and events:read required"});return
 q=parse_qs(query or "");cursor=_first(q,"cursor") or handler.headers.get("Last-Event-ID")
 try:timeout=max(1,min(int(_first(q,"timeout",20)),30));batch=max(1,min(int(_first(q,"batch",100)),250))
 except Exception:timeout=20;batch=100
 repo=RealtimeRepository(backend);repo.initialize();handler.send_response(200);handler.send_header("Content-Type","text/event-stream; charset=utf-8");handler.send_header("Cache-Control","no-cache, no-transform");handler.send_header("Connection","keep-alive");handler.send_header("X-Accel-Buffering","no");handler.end_headers()
 deadline=time.monotonic()+timeout;last_ping=0.0
 try:
  hello=json.dumps({"kind":"CapivaraRealtimeStream","api_version":"v1"},separators=(",",":"));handler.wfile.write(f"event: ready\ndata: {hello}\n\n".encode());handler.wfile.flush()
  while time.monotonic()<deadline:
   page=repo.events(cursor=cursor,limit=batch,event_type=_first(q,"event_type"),agent_id=_first(q,"agent_id"),instance_id=_first(q,"instance_id"),severity=_first(q,"severity"))
   for event in page["events"]:
    cursor=page["cursor"] if event is page["events"][-1] else cursor
    event_cursor=__import__('api_platform').encode_cursor(event["occurred_at"],event["event_id"]);cursor=event_cursor
    payload=json.dumps(event,separators=(",",":"),ensure_ascii=False);handler.wfile.write(f"id: {event_cursor}\nevent: universal-event\ndata: {payload}\n\n".encode())
   now=time.monotonic()
   if page["events"] or now-last_ping>=10:
    if not page["events"]:handler.wfile.write(b": keepalive\n\n")
    handler.wfile.flush();last_ping=now
   if not page["has_more"]:time.sleep(.75)
 except (BrokenPipeError,ConnectionResetError):return

__all__=["API_AUTOMATION_PATH","API_BROADCAST_PATH","API_EVENTS_PATH","API_INSTANCES_PATH","API_OBSERVABILITY_PATH","API_STATUS_PATH","PUBLIC_GET_PATHS","PUBLIC_POST_PATHS","SSE_EVENTS_PATH","dispatch_realtime_get","dispatch_realtime_post","serve_event_stream"]
