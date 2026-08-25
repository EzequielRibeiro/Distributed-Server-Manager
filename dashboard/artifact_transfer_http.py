#!/usr/bin/env python3
"""Binary Artifact Transfer Plane for remote Agents and Customer backups."""
from __future__ import annotations
from pathlib import Path
from urllib.parse import parse_qs,urlparse
import uuid
from agent_pairing_repository import AgentCredentialInvalid,AgentPairingRepository
from artifact_transfer_repository import ArtifactTransferRepository
from backup_repository import BackupRepository
from controller_session import session_user_from_headers
from customer_instance_workspace_service import CustomerInstanceWorkspaceService

AGENT_UPLOAD="/api/agent/artifacts/upload";AGENT_DOWNLOAD="/api/agent/artifacts/download";CUSTOMER_PREFIX="/api/customer/artifacts";CUSTOMER_STATUS=CUSTOMER_PREFIX+"/status";CUSTOMER_DOWNLOAD=CUSTOMER_PREFIX+"/download";CUSTOMER_EXPORT=CUSTOMER_PREFIX+"/backup-export";CUSTOMER_IMPORT=CUSTOMER_PREFIX+"/backup-import";CUSTOMER_UPLOAD=CUSTOMER_PREFIX+"/upload"

def install_artifact_transfer_http(legacy,authenticate):
 previous_get=legacy.DashboardHandler.do_GET;previous_post=legacy.DashboardHandler.do_POST;previous_put=getattr(legacy.DashboardHandler,"do_PUT",None)
 root=Path(legacy.DSM_ROOT)
 def backend():return legacy.dashboard_repository(legacy.DATABASE_FILE).backend
 def repo():return ArtifactTransferRepository(backend(),root)
 def agent(self):
  try:return AgentPairingRepository(backend()).authenticate(credential_id=str(self.headers.get("X-Capivara-Agent-Credential") or ""),credential_secret=str(self.headers.get("X-Capivara-Agent-Secret") or ""),fingerprint=str(self.headers.get("X-Capivara-Agent-Fingerprint") or "") or None)
  except AgentCredentialInvalid:return None
 def actor(self):
  value=session_user_from_headers(self.headers)
  if value is not None:return value
  try:return authenticate(self.headers)
  except Exception:return None
 def one(parsed,name,default=""):return (parse_qs(parsed.query,keep_blank_values=True).get(name) or [default])[0]
 def workspace():return CustomerInstanceWorkspaceService(backend(),root)
 def content_length(self):
  value=str(self.headers.get("Content-Length") or "").strip()
  if not value:raise ValueError("Content-Length is required")
  length=int(value)
  if length<0 or length>64*1024*1024*1024:raise ValueError("artifact exceeds 64 GiB transfer limit")
  return length
 def send_binary(self,path,item):
  size=path.stat().st_size;name=Path(str(item.get("filename") or path.name)).name
  self.send_response(200);self.send_header("Content-Type","application/octet-stream");self.send_header("Content-Length",str(size));self.send_header("Content-Disposition",f'attachment; filename="{name.replace(chr(34),"")}"');self.send_header("Cache-Control","no-store");self.end_headers()
  with path.open("rb") as handle:
   while True:
    chunk=handle.read(1024*1024)
    if not chunk:break
    self.wfile.write(chunk)
 def customer_transfer(user,transfer_id,permission):
  item=repo().get(transfer_id);iid=str(item.get("instance_id") or "")
  if not iid:raise PermissionError("transfer is not attached to an instance")
  workspace().require(user,iid,permission);return item
 def get(self):
  parsed=urlparse(self.path);path=parsed.path
  if path==AGENT_DOWNLOAD:
   identity=agent(self)
   if identity is None:return self.send_json(401,{"error":"agent_authentication_failed"})
   try:
    artifact,item=repo().controller_artifact(one(parsed,"transfer_id"))
    if str(item.get("agent_id"))!=str(identity.get("agent_id")) or item.get("direction")!="controller_to_agent":raise PermissionError("artifact transfer ownership mismatch")
    return send_binary(self,artifact,item)
   except PermissionError:return self.send_json(403,{"error":"forbidden"})
   except (KeyError,FileNotFoundError,ValueError):return self.send_json(404,{"error":"artifact_not_ready"})
  if path not in {CUSTOMER_STATUS,CUSTOMER_DOWNLOAD}:return previous_get(self)
  user=actor(self)
  if user is None:return self.unauthorized()
  try:
   tid=one(parsed,"transfer_id");item=repo().get(tid);purpose=str(item.get("purpose") or "");permission="backup.restore" if purpose in {"backup_import","backup_clone"} else "backup.download";customer_transfer(user,tid,permission)
   if path==CUSTOMER_STATUS:return self.send_json(200,{k:item.get(k) for k in ("transfer_id","instance_id","direction","purpose","filename","status","size_bytes","transferred_bytes","sha256","last_error","expires_at","destination_ref")})
   if str(item.get("status"))!="completed" or item.get("direction")!="agent_to_controller":raise FileNotFoundError("artifact not ready")
   artifact,_=repo().controller_artifact(tid);return send_binary(self,artifact,item)
  except PermissionError:return self.send_json(403,{"error":"forbidden"})
  except (KeyError,FileNotFoundError,ValueError):return self.send_json(404,{"error":"artifact_not_ready"})
 def post(self):
  parsed=urlparse(self.path);path=parsed.path
  if path not in {CUSTOMER_EXPORT,CUSTOMER_IMPORT}:return previous_post(self)
  user=actor(self)
  if user is None:return self.unauthorized()
  try:
   body=self.read_json_body();iid=str(body.get("instance_id") or "").strip();context=workspace().require(user,iid,"backup.download" if path==CUSTOMER_EXPORT else "backup.restore");agent_id=str(context.get("agent_id") or "")
   if path==CUSTOMER_EXPORT:
    backup_id=str(body.get("backup_id") or "").strip();backups=BackupRepository(backend());backups.initialize();job=next((x for x in backups.list_jobs(instance_id=iid,limit=200) if str(x.get("backup_id") or "")==backup_id and x.get("action")=="create" and x.get("status")=="completed"),None)
    if job is None:raise LookupError("completed backup not found")
    filename=Path(str(job.get("artifact_path") or f"{backup_id}.tar.gz")).name;item=repo().create(agent_id=agent_id,instance_id=iid,customer_id=context.get("customer_id"),direction="agent_to_controller",purpose="backup_export",filename=filename,source_ref=backup_id,requested_by=str(user.get("username") or ""),ttl_hours=24)
   else:
    filename=Path(str(body.get("filename") or "backup-upload.tar.gz")).name
    if not filename.lower().endswith((".tar",".tar.gz",".tgz")):raise ValueError("unsupported backup archive")
    backup_id="import-"+uuid.uuid4().hex;item=repo().create(agent_id=agent_id,instance_id=iid,customer_id=context.get("customer_id"),direction="controller_to_agent",purpose="backup_import",filename=filename,destination_ref=backup_id,requested_by=str(user.get("username") or ""),ttl_hours=24)
   return self.send_json(201,{k:item.get(k) for k in ("transfer_id","instance_id","direction","purpose","filename","status","destination_ref","expires_at")})
  except PermissionError:return self.send_json(403,{"error":"forbidden"})
  except (ValueError,LookupError) as exc:return self.send_json(400,{"error":"invalid_request","message":str(exc)})
 def put(self):
  parsed=urlparse(self.path);path=parsed.path
  if path==AGENT_UPLOAD:
   identity=agent(self)
   if identity is None:return self.send_json(401,{"error":"agent_authentication_failed"})
   try:
    tid=one(parsed,"transfer_id");item=repo().get(tid)
    if str(item.get("agent_id"))!=str(identity.get("agent_id")) or item.get("direction")!="agent_to_controller":raise PermissionError("artifact transfer ownership mismatch")
    saved=repo().receive_from_agent(tid,identity["agent_id"],self.rfile,content_length(self));return self.send_json(201,{"transfer_id":tid,"status":saved.get("status"),"size_bytes":saved.get("size_bytes"),"sha256":saved.get("sha256")})
   except PermissionError:return self.send_json(403,{"error":"forbidden"})
   except (KeyError,ValueError) as exc:return self.send_json(400,{"error":"invalid_transfer","message":str(exc)})
  if path!=CUSTOMER_UPLOAD:
   if previous_put is not None:return previous_put(self)
   return self.send_json(404,{"error":"not_found"})
  user=actor(self)
  if user is None:return self.unauthorized()
  try:
   tid=one(parsed,"transfer_id");item=customer_transfer(user,tid,"backup.restore")
   if item.get("direction")!="controller_to_agent":raise ValueError("invalid upload transfer direction")
   saved=repo().stage_from_controller(tid,self.rfile,content_length(self));return self.send_json(201,{"transfer_id":tid,"status":saved.get("status"),"size_bytes":saved.get("size_bytes"),"sha256":saved.get("sha256"),"destination_ref":saved.get("destination_ref")})
  except PermissionError:return self.send_json(403,{"error":"forbidden"})
  except (KeyError,ValueError) as exc:return self.send_json(400,{"error":"invalid_transfer","message":str(exc)})
 legacy.DashboardHandler.do_GET=get;legacy.DashboardHandler.do_POST=post;legacy.DashboardHandler.do_PUT=put

__all__=["AGENT_UPLOAD","AGENT_DOWNLOAD","CUSTOMER_PREFIX","install_artifact_transfer_http"]
