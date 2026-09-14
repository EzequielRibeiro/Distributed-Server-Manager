#!/usr/bin/env python3
"""Backend-neutral desired-state persistence for Universal Content."""
from __future__ import annotations
import json,sys,uuid
from pathlib import Path
from typing import Any,Mapping
ROOT=Path(__file__).resolve().parents[1]; CORE=ROOT/"core"
if str(CORE) not in sys.path: sys.path.insert(0,str(CORE))
from alert_repository import AlertSession
from content_bundle import normalize_bundle
from content_platform import ContentValidationError,normalize_assignment
from event_platform import utc_now

_SECURITY_STATES={"unscanned","clean","suspicious","blocked","scan_failed"}

class ContentRepository:
 def __init__(self,backend): self.backend=backend
 def initialize(self): self.backend.initialize()
 @property
 def ph(self): return "?" if self.backend.name=="sqlite" else "%s"
 def _row(self,row):
  if row is None:return None
  v=dict(row)
  for col,name,default in (("artifact_json","artifact",{}),("provenance_json","provenance",{}),("metadata_json","metadata",{}),("dependencies_json","dependencies",[]),("conflicts_json","conflicts",[])):
   raw=v.pop(col,None)
   try:v[name]=json.loads(raw) if raw is not None else default
   except (TypeError,json.JSONDecodeError):v[name]=default
  desired=str(v.get("desired_state") or "installed");v["activation_state"]=str(v.get("activation_state") or ("enabled" if desired=="installed" else "disabled"));v["activation_order"]=int(v.get("activation_order") or 0);v["security_state"]=str(v.get("security_state") or "unscanned");v["kind"]="CapivaraContentAssignment";v["schema_version"]=2
  return v
 def _instance(self,instance_id):
  with self.backend.connect() as c:
   s=AlertSession(self.backend,c)
   try:return s.execute(f"SELECT id,agent_id,game_id FROM instances WHERE id={self.ph}",(instance_id,)).fetchone()
   finally:s.close()
 def _agent_content_providers(self,agent_id):
  if not agent_id:return None
  with self.backend.connect() as c:
   s=AlertSession(self.backend,c)
   try:row=s.execute(f"SELECT capabilities_json FROM agent_runtime_inventory WHERE agent_id={self.ph}",(agent_id,)).fetchone()
   finally:s.close()
  if row is None:return None
  raw=row["capabilities_json"]
  try:capabilities=raw if isinstance(raw,dict) else json.loads(raw or "{}")
  except (TypeError,json.JSONDecodeError):return None
  if not isinstance(capabilities,dict) or int(capabilities.get("content_provider_contract") or 0)<1:return None
  providers=capabilities.get("content_providers")
  if not isinstance(providers,list):return set()
  return {str(value).strip().lower() for value in providers if str(value).strip()}
 def _preflight_provider(self,agent_id,provider):
  advertised=self._agent_content_providers(agent_id)
  if advertised is None:return
  if str(provider).strip().lower() not in advertised:raise ContentValidationError(f"Agent does not support content provider: {provider}")
 def _prepare_assignment(self,raw,inst):
  body=dict(raw or {});record=dict(inst);agent_id=str(record.get("agent_id") or "").strip();game_id=str(record.get("game_id") or body.get("game_id") or "").strip();body["agent_id"]=agent_id;body["game_id"]=game_id
  item=normalize_assignment(body,expected_agent_id=agent_id);self._preflight_provider(agent_id,item["provider"]);return item
 def _existing_session(self,s,instance_id,content_id):
  return self._row(s.execute(f"SELECT * FROM content_assignments WHERE instance_id={self.ph} AND content_id={self.ph}",(instance_id,content_id)).fetchone())
 def _write_assignment_session(self,s,item,existing,requested_by,now):
  if existing and existing.get("checksum")==item["checksum"]:return existing,False
  aid=str(existing["assignment_id"]) if existing else str(uuid.uuid4());rev=int(existing.get("revision") or 0)+1 if existing else 1
  artifact=json.dumps(item["artifact"],sort_keys=True,separators=(",",":"),ensure_ascii=False);provenance=json.dumps(item["provenance"],sort_keys=True,separators=(",",":"),ensure_ascii=False);metadata=json.dumps(item["metadata"],sort_keys=True,separators=(",",":"),ensure_ascii=False);deps=json.dumps(item["dependencies"],separators=(",",":"));conflicts=json.dumps(item["conflicts"],separators=(",",":"))
  vals=(item["agent_id"],item["game_id"],item["content_type"],item["desired_state"],item["activation_state"],item["activation_order"],item["version"],item["provider"],item["target"],artifact,provenance,metadata,item["security_state"],deps,conflicts,rev,item["checksum"],requested_by,now)
  if existing:s.execute(f"UPDATE content_assignments SET agent_id={self.ph},game_id={self.ph},content_type={self.ph},desired_state={self.ph},activation_state={self.ph},activation_order={self.ph},version={self.ph},provider={self.ph},target={self.ph},artifact_json={self.ph},provenance_json={self.ph},metadata_json={self.ph},security_state={self.ph},dependencies_json={self.ph},conflicts_json={self.ph},revision={self.ph},checksum={self.ph},requested_by={self.ph},updated_at={self.ph} WHERE assignment_id={self.ph}",(*vals,aid))
  else:s.execute(f"INSERT INTO content_assignments(assignment_id,instance_id,agent_id,content_id,game_id,content_type,desired_state,activation_state,activation_order,version,provider,target,artifact_json,provenance_json,metadata_json,security_state,dependencies_json,conflicts_json,revision,checksum,requested_by,created_at,updated_at) VALUES ({','.join([self.ph]*23)})",(aid,item["instance_id"],item["agent_id"],item["content_id"],item["game_id"],item["content_type"],item["desired_state"],item["activation_state"],item["activation_order"],item["version"],item["provider"],item["target"],artifact,provenance,metadata,item["security_state"],deps,conflicts,rev,item["checksum"],requested_by,now,now))
  s.execute(f"INSERT INTO content_assignment_revisions(assignment_id,revision,desired_state,activation_state,activation_order,version,provider,target,artifact_json,provenance_json,metadata_json,security_state,dependencies_json,conflicts_json,checksum,requested_by,created_at) VALUES ({','.join([self.ph]*17)})",(aid,rev,item["desired_state"],item["activation_state"],item["activation_order"],item["version"],item["provider"],item["target"],artifact,provenance,metadata,item["security_state"],deps,conflicts,item["checksum"],requested_by,now))
  return {**item,"assignment_id":aid,"revision":rev,"requested_by":requested_by,"created_at":existing.get("created_at") if existing else now,"updated_at":now},True
 def get(self,instance_id,content_id):
  with self.backend.connect() as c:
   s=AlertSession(self.backend,c)
   try:return self._existing_session(s,instance_id,content_id)
   finally:s.close()
 def put(self,raw:Mapping[str,Any],*,requested_by:str|None=None):
  body=dict(raw or {});instance_id=str(body.get("instance_id") or "").strip();inst=self._instance(instance_id)
  if inst is None:raise ContentValidationError("instance does not exist")
  item=self._prepare_assignment(body,inst);now=utc_now()
  with self.backend.transaction() as c:
   s=AlertSession(self.backend,c)
   try:stored,changed=self._write_assignment_session(s,item,self._existing_session(s,item["instance_id"],item["content_id"]),requested_by,now)
   finally:s.close()
  return {"assignment":self.get(item["instance_id"],item["content_id"]),"changed":changed}
 def put_bundle(self,parent_raw:Mapping[str,Any],bundle_raw:Mapping[str,Any],children_raw:list[Mapping[str,Any]],*,requested_by:str|None=None):
  parent_body=dict(parent_raw or {});instance_id=str(parent_body.get("instance_id") or "").strip();inst=self._instance(instance_id)
  if inst is None:raise ContentValidationError("instance does not exist")
  if str(dict(inst).get("game_id") or "").strip().lower()!="minecraft":raise ContentValidationError("content bundles currently require Minecraft")
  bundle_input=dict(bundle_raw or {});bundle_input["instance_id"]=instance_id;bundle_input["parent_content_id"]=str(parent_body.get("content_id") or "").strip();bundle=normalize_bundle(bundle_input)
  bundle_meta={"parent_content_id":bundle["parent_content_id"],"manifest_sha256":bundle["manifest_sha256"],"provider":bundle["provider"],"provider_project_id":bundle["provider_project_id"],"provider_version_id":bundle["provider_version_id"]}
  metadata=dict(parent_body.get("metadata") or {});metadata["bundle"]=bundle_meta;metadata["activation"]={"adapter":"minecraft-java","mode":"bundle-parent","identifier":",".join(bundle["override_roots"])};parent_body["metadata"]=metadata;parent_body["content_type"]="modpack";parent_body["desired_state"]="installed";parent_body["activation_state"]="enabled"
  parent=self._prepare_assignment(parent_body,inst)
  children=[]
  for raw in children_raw:
   body=dict(raw or {});body["instance_id"]=instance_id;meta=dict(body.get("metadata") or {});meta["bundle"]=bundle_meta;body["metadata"]=meta;body["desired_state"]="installed";children.append(self._prepare_assignment(body,inst))
  manifest_members={str(item.get("content_id") or ""):item for item in bundle["manifest"]["members"]};member_ids=set(manifest_members);child_ids={item["content_id"] for item in children}
  if member_ids!=child_ids:raise ContentValidationError("bundle members do not match child assignments")
  if len(child_ids)!=len(children):raise ContentValidationError("duplicate bundle child content_id")
  if parent["content_id"] in child_ids:raise ContentValidationError("bundle parent cannot also be a child")
  if parent["provider"]!=bundle["provider"]:raise ContentValidationError("bundle parent provider mismatch")
  for child in children:
   member=manifest_members[child["content_id"]]
   if child["content_type"]!="mod" or child["target"]!=f"mods/{child['content_id']}":raise ContentValidationError("bundle child must be a managed mod target")
   if child["provider"]!=bundle["provider"] or child["artifact"]!=member["artifact"]:raise ContentValidationError("bundle child artifact does not match manifest")
  now=utc_now();changed_any=False
  with self.backend.transaction() as c:
   s=AlertSession(self.backend,c)
   try:
    existing_bundle_row=s.execute(f"SELECT * FROM content_bundles WHERE instance_id={self.ph} AND parent_content_id={self.ph}",(instance_id,parent["content_id"])).fetchone();existing_bundle=dict(existing_bundle_row) if existing_bundle_row else None
    old_ids=set()
    if existing_bundle:
     prior=s.execute(f"SELECT manifest_json FROM content_bundle_revisions WHERE bundle_id={self.ph} AND revision={self.ph}",(existing_bundle["bundle_id"],existing_bundle["revision"])).fetchone()
     if prior:
      try:old_manifest=json.loads(prior["manifest_json"] or "{}")
      except (TypeError,json.JSONDecodeError):raise ContentValidationError("stored bundle manifest is invalid")
      old_ids={str(item.get("content_id") or "") for item in old_manifest.get("members") or [] if isinstance(item,dict) and item.get("content_id")}
    existing_parent=self._existing_session(s,instance_id,parent["content_id"])
    if existing_parent:
     if not existing_bundle:raise ContentValidationError("bundle parent content_id is already owned by non-bundle content")
     if str(existing_bundle.get("parent_assignment_id") or "")!=str(existing_parent.get("assignment_id") or ""):raise ContentValidationError("bundle parent ownership mismatch")
    parent_stored,parent_changed=self._write_assignment_session(s,parent,existing_parent,requested_by,now);changed_any|=parent_changed
    for child in children:
     existing_child=self._existing_session(s,instance_id,child["content_id"])
     if existing_child:
      marker=(existing_child.get("metadata") or {}).get("bundle") if isinstance(existing_child.get("metadata"),dict) else None
      if not isinstance(marker,dict) or str(marker.get("parent_content_id") or "")!=parent["content_id"]:raise ContentValidationError("bundle child content_id is already owned by other content")
     stored,changed=self._write_assignment_session(s,child,existing_child,requested_by,now);changed_any|=changed
    for stale_id in sorted(old_ids-child_ids):
     existing=self._existing_session(s,instance_id,stale_id)
     if not existing:continue
     bundle_marker=(existing.get("metadata") or {}).get("bundle") if isinstance(existing.get("metadata"),dict) else None
     if not isinstance(bundle_marker,dict) or str(bundle_marker.get("parent_content_id") or "")!=parent["content_id"]:raise ContentValidationError("refusing to remove content not owned by this bundle")
     stale_raw={key:existing.get(key) for key in ("instance_id","content_id","content_type","version","provider","target","artifact","provenance","metadata","dependencies","conflicts","activation_order")};stale_raw["desired_state"]="absent";stale_raw["activation_state"]="disabled";stale=self._prepare_assignment(stale_raw,inst);_,changed=self._write_assignment_session(s,stale,existing,requested_by,now);changed_any|=changed
    bundle_changed=not existing_bundle or str(existing_bundle.get("checksum") or "")!=bundle["checksum"]
    bundle_id=str(existing_bundle["bundle_id"]) if existing_bundle else str(uuid.uuid4());bundle_revision=int(existing_bundle.get("revision") or 0)+1 if existing_bundle and bundle_changed else 1 if not existing_bundle else int(existing_bundle["revision"])
    roots_json=json.dumps(bundle["override_roots"],separators=(",",":"));manifest_json=json.dumps(bundle["manifest"],sort_keys=True,separators=(",",":"),ensure_ascii=False)
    if bundle_changed:
     values=(instance_id,parent_stored["assignment_id"],parent["content_id"],bundle["provider"],bundle["provider_project_id"],bundle["provider_version_id"],bundle["minecraft_version"],bundle["loader_id"],bundle["loader_version"],bundle["manifest_kind"],bundle["manifest_sha256"],roots_json,bundle_revision,bundle["checksum"],requested_by,now)
     if existing_bundle:s.execute(f"UPDATE content_bundles SET instance_id={self.ph},parent_assignment_id={self.ph},parent_content_id={self.ph},provider={self.ph},provider_project_id={self.ph},provider_version_id={self.ph},minecraft_version={self.ph},loader_id={self.ph},loader_version={self.ph},manifest_kind={self.ph},manifest_sha256={self.ph},override_roots_json={self.ph},revision={self.ph},checksum={self.ph},requested_by={self.ph},updated_at={self.ph} WHERE bundle_id={self.ph}",(*values,bundle_id))
     else:s.execute(f"INSERT INTO content_bundles(bundle_id,instance_id,parent_assignment_id,parent_content_id,provider,provider_project_id,provider_version_id,minecraft_version,loader_id,loader_version,manifest_kind,manifest_sha256,override_roots_json,revision,checksum,requested_by,created_at,updated_at) VALUES ({','.join([self.ph]*18)})",(bundle_id,*values,now))
     s.execute(f"INSERT INTO content_bundle_revisions(bundle_id,revision,parent_assignment_id,provider,provider_project_id,provider_version_id,minecraft_version,loader_id,loader_version,manifest_kind,manifest_sha256,manifest_json,override_roots_json,checksum,requested_by,created_at) VALUES ({','.join([self.ph]*16)})",(bundle_id,bundle_revision,parent_stored["assignment_id"],bundle["provider"],bundle["provider_project_id"],bundle["provider_version_id"],bundle["minecraft_version"],bundle["loader_id"],bundle["loader_version"],bundle["manifest_kind"],bundle["manifest_sha256"],manifest_json,roots_json,bundle["checksum"],requested_by,now));changed_any=True
   finally:s.close()
  return {"bundle_id":bundle_id,"bundle_revision":bundle_revision,"manifest_sha256":bundle["manifest_sha256"],"assignment":self.get(instance_id,parent["content_id"]),"children":[self.get(instance_id,cid) for cid in sorted(child_ids)],"changed":changed_any}
 def set_bundle_state(self,instance_id,parent_content_id,*,desired_state="installed",activation_state="enabled",requested_by=None):
  inst=self._instance(instance_id)
  if inst is None:raise ContentValidationError("instance does not exist")
  if desired_state not in {"installed","absent"} or activation_state not in {"enabled","disabled"}:raise ContentValidationError("invalid bundle state")
  if desired_state=="absent" and activation_state!="disabled":raise ContentValidationError("absent bundle cannot be enabled")
  now=utc_now();changed_any=False;ids=[]
  with self.backend.transaction() as c:
   s=AlertSession(self.backend,c)
   try:
    bundle_row=s.execute(f"SELECT * FROM content_bundles WHERE instance_id={self.ph} AND parent_content_id={self.ph}",(instance_id,parent_content_id)).fetchone()
    if bundle_row is None:raise ContentValidationError("content bundle does not exist")
    bundle=dict(bundle_row);revision=s.execute(f"SELECT manifest_json FROM content_bundle_revisions WHERE bundle_id={self.ph} AND revision={self.ph}",(bundle["bundle_id"],bundle["revision"])).fetchone()
    if revision is None:raise ContentValidationError("content bundle revision is unavailable")
    try:manifest=json.loads(revision["manifest_json"] or "{}")
    except (TypeError,json.JSONDecodeError) as exc:raise ContentValidationError("stored bundle manifest is invalid") from exc
    ids=[parent_content_id,*[str(item.get("content_id") or "") for item in manifest.get("members") or [] if isinstance(item,dict) and item.get("content_id")]]
    for cid in ids:
     existing=self._existing_session(s,instance_id,cid)
     if not existing:raise ContentValidationError("bundle assignment is missing")
     if cid!=parent_content_id:
      marker=(existing.get("metadata") or {}).get("bundle") if isinstance(existing.get("metadata"),dict) else None
      if not isinstance(marker,dict) or str(marker.get("parent_content_id") or "")!=parent_content_id:raise ContentValidationError("bundle child ownership mismatch")
     raw={key:existing.get(key) for key in ("instance_id","content_id","content_type","version","provider","target","artifact","provenance","metadata","dependencies","conflicts","activation_order")};raw["desired_state"]=desired_state;raw["activation_state"]=activation_state;item=self._prepare_assignment(raw,inst);_,changed=self._write_assignment_session(s,item,existing,requested_by,now);changed_any|=changed
   finally:s.close()
  return {"assignment":self.get(instance_id,parent_content_id),"children":[self.get(instance_id,cid) for cid in ids[1:]],"changed":changed_any}
 def list(self,*,agent_id=None,instance_id=None,desired_state=None,limit=500):
  clauses=[];params=[]
  for col,val in (("agent_id",agent_id),("instance_id",instance_id),("desired_state",desired_state)):
   if val:clauses.append(f"{col}={self.ph}");params.append(val)
  where=" WHERE "+" AND ".join(clauses) if clauses else "";params.append(max(1,min(int(limit),2000)))
  with self.backend.connect() as c:
   s=AlertSession(self.backend,c)
   try:return [self._row(r) for r in s.execute(f"SELECT * FROM content_assignments{where} ORDER BY instance_id,activation_order,content_id LIMIT {self.ph}",tuple(params)).fetchall()]
   finally:s.close()
 def history(self,assignment_id):
  with self.backend.connect() as c:
   s=AlertSession(self.backend,c)
   try:
    out=[]
    for row in s.execute(f"SELECT * FROM content_assignment_revisions WHERE assignment_id={self.ph} ORDER BY revision DESC",(assignment_id,)).fetchall():
     v=dict(row)
     for col,name,default in (("artifact_json","artifact",{}),("provenance_json","provenance",{}),("metadata_json","metadata",{}),("dependencies_json","dependencies",[]),("conflicts_json","conflicts",[])):
      raw=v.pop(col,None)
      try:v[name]=json.loads(raw) if raw is not None else default
      except Exception:v[name]=default
     desired=str(v.get("desired_state") or "installed");v["activation_state"]=str(v.get("activation_state") or ("enabled" if desired=="installed" else "disabled"));v["activation_order"]=int(v.get("activation_order") or 0);v["security_state"]=str(v.get("security_state") or "unscanned");v["schema_version"]=2;out.append(v)
    return out
   finally:s.close()
 def _applied(self,agent_id):
  with self.backend.connect() as c:
   s=AlertSession(self.backend,c)
   try:return {(str(r["instance_id"]),str(r["content_id"])):(int(r["applied_revision"] or 0),str(r["applied_checksum"] or ""),str(r["status"] or "")) for r in s.execute(f"SELECT * FROM agent_content_state WHERE agent_id={self.ph}",(agent_id,)).fetchall()}
   finally:s.close()
 def desired_for_agent(self,agent_id):
  applied=self._applied(agent_id);out=[]
  for a in self.list(agent_id=agent_id,limit=2000):
   state=applied.get((a["instance_id"],a["content_id"]))
   if state==(int(a["revision"]),str(a["checksum"]),"applied"):continue
   out.append(a)
  return out
 def record_agent_state(self,agent_id,reports:list[Mapping[str,Any]]):
  accepted=0;now=utc_now()
  with self.backend.transaction() as c:
   s=AlertSession(self.backend,c)
   try:
    for r in reports[:2000]:
     iid=str(r.get("instance_id") or "");cid=str(r.get("content_id") or "");inst=self._instance(iid)
     if not inst or str(dict(inst)["agent_id"] or "")!=agent_id or not cid:continue
     desired_rev=int(r.get("desired_revision") or r.get("applied_revision") or 0);desired_sum=str(r.get("desired_checksum") or r.get("applied_checksum") or "")
     if not desired_rev or not desired_sum:continue
     security_state=str(r.get("security_state") or "unscanned").strip().lower()
     if security_state not in _SECURITY_STATES:continue
     existing=s.execute(f"SELECT agent_id FROM agent_content_state WHERE agent_id={self.ph} AND instance_id={self.ph} AND content_id={self.ph}",(agent_id,iid,cid)).fetchone();vals=(desired_rev,int(r.get("applied_revision") or 0) or None,desired_sum,str(r.get("applied_checksum") or "") or None,str(r.get("status") or "unknown"),r.get("installed_version"),security_state,r.get("last_error"),r.get("reported_at") or now,now)
     if existing:s.execute(f"UPDATE agent_content_state SET desired_revision={self.ph},applied_revision={self.ph},desired_checksum={self.ph},applied_checksum={self.ph},status={self.ph},installed_version={self.ph},security_state={self.ph},last_error={self.ph},reported_at={self.ph},updated_at={self.ph} WHERE agent_id={self.ph} AND instance_id={self.ph} AND content_id={self.ph}",(*vals,agent_id,iid,cid))
     else:s.execute(f"INSERT INTO agent_content_state(agent_id,instance_id,content_id,desired_revision,applied_revision,desired_checksum,applied_checksum,status,installed_version,security_state,last_error,reported_at,updated_at) VALUES ({','.join([self.ph]*13)})",(agent_id,iid,cid,*vals))
     accepted+=1
   finally:s.close()
  return accepted

__all__=["ContentRepository"]
