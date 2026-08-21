#!/usr/bin/env python3
"""Administrative HTTP boundary for D2 API credentials."""
from __future__ import annotations
from urllib.parse import parse_qs
from api_access_repository import ApiAccessRepository
from api_platform import ApiValidationError
API_TOKENS_PATH="/api/api-tokens"
def _admin(user):
 actor=user if isinstance(user,dict) else {}
 if str(actor.get("role") or "").lower() not in {"admin","controller"}:raise PermissionError("administrator access required")
 return actor
def dispatch_api_access_get(path,query,*,user,backend):
 try:
  _admin(user)
  if path!=API_TOKENS_PATH:return 404,{"error":"not_found"}
  r=ApiAccessRepository(backend);r.initialize();rows=r.list_tokens();return 200,{"schema_version":1,"kind":"CapivaraApiTokenList","tokens":rows,"count":len(rows)}
 except PermissionError as exc:return 403,{"error":"forbidden","message":str(exc)}
def dispatch_api_access_post(path,payload,*,user,backend):
 try:
  actor=_admin(user);body=dict(payload or {});r=ApiAccessRepository(backend);r.initialize();op=str(body.get("operation") or "create").lower()
  if path!=API_TOKENS_PATH:return 404,{"error":"not_found"}
  if op=="create":return 201,r.create_token(name=body.get("name"),scopes=body.get("scopes"),expires_at=body.get("expires_at"),created_by=str(actor.get("username") or actor.get("id") or "admin"))
  if op=="revoke":
   item=r.revoke(str(body.get("token_id") or ""));return (200,item) if item else (404,{"error":"not_found"})
  return 400,{"error":"invalid_request","message":"unsupported operation"}
 except PermissionError as exc:return 403,{"error":"forbidden","message":str(exc)}
 except (ApiValidationError,ValueError) as exc:return 400,{"error":"invalid_request","message":str(exc)}
__all__=["API_TOKENS_PATH","dispatch_api_access_get","dispatch_api_access_post"]
