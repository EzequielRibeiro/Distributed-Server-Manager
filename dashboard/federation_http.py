#!/usr/bin/env python3
"""HTTP surface for E1 federation administration and Controller peers."""
from __future__ import annotations
from typing import Any,Mapping
from federation import FederationController,FederationPlacementRequest,FederationRoute
from federation_repository import FederationRepository
from universal_event_repository import UniversalEventRepository

FEDERATION_ADMIN_PATH="/api/federation"
FEDERATION_SNAPSHOT_PATH="/api/federation/v1/snapshot"
FEDERATION_EVENTS_PATH="/api/federation/v1/events"
FEDERATION_PEER_PATHS={FEDERATION_SNAPSHOT_PATH,FEDERATION_EVENTS_PATH}

def _is_admin(user):return bool(user) and str(user.get("role") or "").lower() in {"admin","controller"}
def _bearer(headers):
 value=str(headers.get("Authorization") or "")
 if not value.lower().startswith("bearer "):raise PermissionError("federation bearer credential required")
 return value.split(None,1)[1]
def _principal(repo,headers):
 return repo.authenticate_peer(_bearer(headers),request_timestamp=str(headers.get("X-Capivara-Federation-Timestamp") or ""),nonce=str(headers.get("X-Capivara-Federation-Nonce") or ""))

def dispatch_federation_get(path,query,*,user,backend):
 if path!=FEDERATION_ADMIN_PATH:return None
 if not user:return 401,{"error":"authentication required"}
 repo=FederationRepository(backend);repo.initialize();mode=str(query or {}).get("mode","status") if isinstance(query,dict) else "status"
 if isinstance(mode,list):mode=mode[0]
 if mode=="inventory":return 200,repo.global_inventory()
 if mode=="members":return 200,{"members":repo.list_controllers(include_disabled=True)}
 if mode=="routes":return 200,{"routes":repo.list_routes()}
 if mode=="handoffs":return 200,{"handoffs":repo.list_handoffs()}
 changed=repo.refresh_health();members=repo.list_controllers(include_disabled=True);return 200,{"kind":"FederationStatus","members":members,"changed":changed}

def dispatch_federation_post(path,payload,*,user,backend):
 if path!=FEDERATION_ADMIN_PATH:return None
 if not _is_admin(user):return 403,{"error":"admin or controller role required"}
 payload=payload or {};action=str(payload.get("action") or "");repo=FederationRepository(backend);repo.initialize()
 try:
  if action=="peer-add":out=repo.upsert_controller(FederationController(str(payload.get("controller_id") or ""),str(payload.get("endpoint") or ""),payload.get("region_id"),payload.get("datacenter_id"),str(payload.get("role") or "datacenter"),"pending",int(payload.get("priority") or 100)))
  elif action=="peer-disable":out=repo.set_controller_status(str(payload.get("controller_id") or ""),"disabled")
  elif action=="credential-issue":out=repo.issue_credential(str(payload.get("controller_id") or ""),expires_at=payload.get("expires_at"))
  elif action=="credential-revoke":out=repo.revoke_credential(str(payload.get("credential_id") or ""))
  elif action=="route-set":out=repo.upsert_route(FederationRoute(str(payload.get("scope_type") or ""),str(payload.get("scope_id") or ""),str(payload.get("controller_id") or ""),int(payload.get("priority") or 100),bool(payload.get("enabled",True))))
  elif action=="handoff-create":out=repo.create_handoff(FederationPlacementRequest(str(payload.get("request_id") or ""),str(payload.get("instance_id") or ""),str(payload.get("game_id") or ""),payload.get("customer_id"),payload.get("region_id"),payload.get("datacenter_id"),str(payload.get("mode") or "local_first"),bool(payload.get("cross_region_fallback",False))))
  elif action=="health-refresh":out={"changed":repo.refresh_health()}
  else:return 400,{"error":"unsupported federation action"}
  return 200,out
 except LookupError as exc:return 409,{"error":str(exc)}
 except (ValueError,PermissionError) as exc:return 400,{"error":str(exc)}

def dispatch_federation_peer_post(path,payload,*,headers:Mapping[str,Any],backend):
 if path not in FEDERATION_PEER_PATHS:return None
 repo=FederationRepository(backend);repo.initialize()
 try:principal=_principal(repo,headers)
 except PermissionError as exc:return 401,{"error":str(exc)}
 controller_id=str(principal["controller_id"])
 try:
  if path==FEDERATION_SNAPSHOT_PATH:return 202,repo.store_snapshot(controller_id,payload or {})
  events=UniversalEventRepository(backend);events.initialize();return 202,repo.ingest_event_batch(controller_id,payload or {},events)
 except ValueError as exc:return 409,{"error":str(exc)}
 except Exception:return 500,{"error":"federation peer request failed"}

__all__=["FEDERATION_ADMIN_PATH","FEDERATION_EVENTS_PATH","FEDERATION_PEER_PATHS","FEDERATION_SNAPSHOT_PATH","dispatch_federation_get","dispatch_federation_peer_post","dispatch_federation_post"]
