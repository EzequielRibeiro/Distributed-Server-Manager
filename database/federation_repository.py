#!/usr/bin/env python3
"""Backend-neutral persistence for E1 Multi-Datacenter Federation."""
from __future__ import annotations
import hashlib,json,secrets,sys
from pathlib import Path
from typing import Any,Mapping
ROOT=Path(__file__).resolve().parents[1];CORE=ROOT/"core"
if str(CORE) not in sys.path:sys.path.insert(0,str(CORE))
from alert_repository import AlertSession
from federation import FederationMember,build_inventory_snapshot,utc_now,validate_id

class FederationRepository:
 def __init__(self,backend):self.backend=backend
 def initialize(self):self.backend.initialize()
 @property
 def ph(self):return "?" if self.backend.name=="sqlite" else "%s"
 @staticmethod
 def _row(row):
  if row is None:return None
  value=dict(row)
  for key in ("payload_json",):
   if key in value:
    try:value["payload"]=json.loads(value.pop(key) or "{}")
    except (TypeError,json.JSONDecodeError):value["payload"]={}
  return value
 def list_members(self,status=None):
  with self.backend.connect() as c:
   s=AlertSession(self.backend,c);sql="SELECT * FROM federation_members";params=[]
   if status:sql+=f" WHERE status={self.ph}";params.append(status)
   sql+=" ORDER BY controller_id";return [dict(r) for r in s.execute(sql,tuple(params)).fetchall()]
 def put_member(self,raw:Mapping[str,Any],credential_hash=None):
  member=FederationMember(**{k:raw.get(k) for k in ("controller_id","role","region_id","datacenter_id","public_endpoint","status")}).normalized();now=utc_now()
  with self.backend.transaction() as c:
   s=AlertSession(self.backend,c);old=s.execute(f"SELECT controller_id FROM federation_members WHERE controller_id={self.ph}",(member["controller_id"],)).fetchone()
   values=(member["role"],member["region_id"],member["datacenter_id"],member["public_endpoint"],credential_hash,member["status"],now)
   if old:s.execute(f"UPDATE federation_members SET role={self.ph},region_id={self.ph},datacenter_id={self.ph},public_endpoint={self.ph},credential_hash=COALESCE({self.ph},credential_hash),status={self.ph},updated_at={self.ph} WHERE controller_id={self.ph}",(*values,member["controller_id"]))
   else:s.execute(f"INSERT INTO federation_members(controller_id,role,region_id,datacenter_id,public_endpoint,credential_hash,status,created_at,updated_at) VALUES ({','.join([self.ph]*9)})",(member["controller_id"],*values[:-1],now,now))
  return member
 def issue_credential(self,controller_id):
  controller_id=validate_id(controller_id,"controller_id");secret="capfed_"+secrets.token_urlsafe(32);digest=hashlib.sha256(secret.encode()).hexdigest();now=utc_now()
  with self.backend.transaction() as c:
   s=AlertSession(self.backend,c);cur=s.execute(f"UPDATE federation_members SET credential_hash={self.ph},updated_at={self.ph} WHERE controller_id={self.ph}",(digest,now,controller_id))
   if getattr(cur,"rowcount",1)==0:raise ValueError("federation member not found")
  return {"controller_id":controller_id,"credential":secret}
 def authenticate(self,controller_id,secret):
  digest=hashlib.sha256(str(secret or "").encode()).hexdigest()
  with self.backend.connect() as c:
   s=AlertSession(self.backend,c);row=s.execute(f"SELECT credential_hash,status FROM federation_members WHERE controller_id={self.ph}",(controller_id,)).fetchone()
  return bool(row and row["status"] in ("active","degraded") and secrets.compare_digest(str(row["credential_hash"] or ""),digest))
 def ingest_snapshot(self,controller_id,raw):
  controller_id=validate_id(controller_id,"controller_id");snapshot=build_inventory_snapshot(controller_id=controller_id,generated_at=raw.get("generated_at"),agents=list(raw.get("agents") or []),instances=list(raw.get("instances") or []),capacity=dict(raw.get("capacity") or {}));now=utc_now();payload=json.dumps(snapshot,sort_keys=True,separators=(",",":"))
  with self.backend.transaction() as c:
   s=AlertSession(self.backend,c);exists=s.execute(f"SELECT snapshot_id FROM federation_inventory_snapshots WHERE snapshot_id={self.ph}",(snapshot["snapshot_id"],)).fetchone()
   if not exists:s.execute(f"INSERT INTO federation_inventory_snapshots(snapshot_id,controller_id,generated_at,payload_json,received_at) VALUES ({','.join([self.ph]*5)})",(snapshot["snapshot_id"],controller_id,snapshot["generated_at"],payload,now))
   s.execute(f"UPDATE federation_members SET last_seen_at={self.ph},status='active',updated_at={self.ph} WHERE controller_id={self.ph}",(now,now,controller_id))
  return snapshot
 def latest_inventory(self):
  with self.backend.connect() as c:
   s=AlertSession(self.backend,c);rows=s.execute("SELECT f.* FROM federation_inventory_snapshots f JOIN (SELECT controller_id,MAX(generated_at) generated_at FROM federation_inventory_snapshots GROUP BY controller_id) x ON x.controller_id=f.controller_id AND x.generated_at=f.generated_at ORDER BY f.controller_id").fetchall()
  return [self._row(r) for r in rows]
 def put_policy(self,raw):
  scope_type=str(raw.get("scope_type") or "global");scope_id=raw.get("scope_id");mode=str(raw.get("mode") or "local_first");
  if scope_type not in {"global","region","datacenter","customer"}:raise ValueError("invalid scope_type")
  if mode not in {"local_first","region_first","global"}:raise ValueError("invalid mode")
  policy_id=str(raw.get("policy_id") or f"fp_{scope_type}_{scope_id or 'global'}");now=utc_now();payload=json.dumps(raw.get("payload") or {},sort_keys=True,separators=(",",":"));cross=1 if raw.get("cross_region_fallback") else 0
  with self.backend.transaction() as c:
   s=AlertSession(self.backend,c);old=s.execute(f"SELECT revision FROM federation_policies WHERE policy_id={self.ph}",(policy_id,)).fetchone();rev=(int(old["revision"])+1) if old else 1
   if old:s.execute(f"UPDATE federation_policies SET scope_type={self.ph},scope_id={self.ph},mode={self.ph},cross_region_fallback={self.ph},max_latency_ms={self.ph},payload_json={self.ph},revision={self.ph},updated_at={self.ph} WHERE policy_id={self.ph}",(scope_type,scope_id,mode,cross,raw.get("max_latency_ms"),payload,rev,now,policy_id))
   else:s.execute(f"INSERT INTO federation_policies(policy_id,scope_type,scope_id,mode,cross_region_fallback,max_latency_ms,payload_json,revision,created_at,updated_at) VALUES ({','.join([self.ph]*10)})",(policy_id,scope_type,scope_id,mode,cross,raw.get("max_latency_ms"),payload,rev,now,now))
  return {"policy_id":policy_id,"scope_type":scope_type,"scope_id":scope_id,"mode":mode,"revision":rev}
