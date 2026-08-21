#!/usr/bin/env python3
"""Backend-neutral API credentials, authorization and request audit."""
from __future__ import annotations
import json
import sys
import uuid
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
ROOT=Path(__file__).resolve().parents[1];CORE=ROOT/"core"
if str(CORE) not in sys.path:sys.path.insert(0,str(CORE))
from alert_repository import AlertSession
from api_platform import ApiValidationError,issue_secret,normalize_scopes,split_token,verify_secret
from event_platform import utc_now

class ApiAccessRepository:
 def __init__(self,backend):self.backend=backend
 def initialize(self):self.backend.initialize()
 @property
 def ph(self):return "?" if self.backend.name=="sqlite" else "%s"
 def _row(self,row):
  if row is None:return None
  value=dict(row)
  try:value["scopes"]=json.loads(value.pop("scopes_json") or "[]")
  except Exception:value["scopes"]=[]
  value.pop("secret_hash",None);return value
 def create_token(self,*,name:str,scopes=None,expires_at=None,created_by=None):
  name=str(name or "").strip()
  if not name or len(name)>191:raise ApiValidationError("invalid token name")
  scope_list=normalize_scopes(scopes);token_id="api-"+uuid.uuid4().hex;prefix,presented,digest=issue_secret(token_id);now=utc_now()
  if expires_at:
   try:
    exp=datetime.fromisoformat(str(expires_at).replace("Z","+00:00"))
    if exp.tzinfo is None:exp=exp.replace(tzinfo=timezone.utc)
    if exp<=datetime.now(timezone.utc):raise ValueError
   except Exception as exc:raise ApiValidationError("expires_at must be a future ISO-8601 timestamp") from exc
  with self.backend.transaction() as c:
   s=AlertSession(self.backend,c)
   try:s.execute(f"INSERT INTO api_tokens(token_id,name,token_prefix,secret_hash,scopes_json,status,expires_at,created_by,created_at) VALUES ({','.join([self.ph]*9)})",(token_id,name,prefix,digest,json.dumps(scope_list,separators=(",",":")),"active",expires_at,created_by,now))
   finally:s.close()
  item=self.get(token_id);item["token"]=presented;return item
 def get(self,token_id):
  with self.backend.connect() as c:
   s=AlertSession(self.backend,c)
   try:return self._row(s.execute(f"SELECT * FROM api_tokens WHERE token_id={self.ph}",(token_id,)).fetchone())
   finally:s.close()
 def list_tokens(self,limit=200):
  with self.backend.connect() as c:
   s=AlertSession(self.backend,c)
   try:return [self._row(r) for r in s.execute(f"SELECT * FROM api_tokens ORDER BY created_at DESC LIMIT {self.ph}",(max(1,min(int(limit),1000)),)).fetchall()]
   finally:s.close()
 def revoke(self,token_id):
  now=utc_now()
  with self.backend.transaction() as c:
   s=AlertSession(self.backend,c)
   try:s.execute(f"UPDATE api_tokens SET status='revoked',revoked_at={self.ph} WHERE token_id={self.ph} AND status='active'",(now,token_id))
   finally:s.close()
  return self.get(token_id)
 def authenticate(self,presented_token:str):
  prefix,secret=split_token(presented_token)
  with self.backend.connect() as c:
   s=AlertSession(self.backend,c)
   try:row=s.execute(f"SELECT * FROM api_tokens WHERE token_prefix={self.ph}",(prefix,)).fetchone()
   finally:s.close()
  if row is None:raise PermissionError("invalid API credential")
  raw=dict(row)
  if str(raw.get("status"))!="active" or not verify_secret(secret,raw.get("secret_hash")):raise PermissionError("invalid API credential")
  if raw.get("expires_at"):
   try:
    exp=datetime.fromisoformat(str(raw["expires_at"]).replace("Z","+00:00"));exp=exp if exp.tzinfo else exp.replace(tzinfo=timezone.utc)
    if exp<=datetime.now(timezone.utc):raise PermissionError("API credential expired")
   except PermissionError:raise
   except Exception:raise PermissionError("API credential expired")
  now=utc_now()
  with self.backend.transaction() as c:
   s=AlertSession(self.backend,c)
   try:s.execute(f"UPDATE api_tokens SET last_used_at={self.ph} WHERE token_id={self.ph}",(now,raw["token_id"]))
   finally:s.close()
  value=self._row(raw);value["principal_type"]="api_token";return value
 def record_request(self,*,token_id=None,method,path,status_code,latency_ms=None,remote_address=None,request_id=None):
  rid=str(request_id or uuid.uuid4());now=utc_now()
  with self.backend.transaction() as c:
   s=AlertSession(self.backend,c)
   try:s.execute(f"INSERT INTO api_request_log(request_id,token_id,method,path,status_code,latency_ms,remote_address,created_at) VALUES ({','.join([self.ph]*8)})",(rid,token_id,str(method)[:16],str(path)[:512],int(status_code),float(latency_ms) if latency_ms is not None else None,str(remote_address)[:191] if remote_address else None,now))
   finally:s.close()
  return rid

__all__=["ApiAccessRepository"]
