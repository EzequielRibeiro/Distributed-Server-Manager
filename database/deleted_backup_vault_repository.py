#!/usr/bin/env python3
"""Persistent distributed vault for final backups created before instance removal."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import uuid
from alert_repository import AlertSession,dialect_for_backend
from agent_instance_runtime_repository import AgentInstanceRuntimeRepository
from artifact_transfer_repository import ArtifactTransferRepository
from backup_repository import BackupRepository
ACTIVE={"backup_pending","export_pending","removal_pending"};FINAL={"ready","expired","failed","removal_failed","deleted"}
def _now():return datetime.now(timezone.utc)
def _iso(value):return value.isoformat().replace("+00:00","Z")
class DeletedBackupVaultRepository:
 def __init__(self,backend,root:Path):
  self.backend=backend;self.root=Path(root).resolve();self.dialect=dialect_for_backend(backend);self.backups=BackupRepository(backend);self.artifacts=ArtifactTransferRepository(backend,self.root);self.runtime=AgentInstanceRuntimeRepository(backend)
 @contextmanager
 def session(self,transaction=False):
  context=self.backend.transaction() if transaction else self.backend.connect()
  with context as connection:
   session=AlertSession(self.backend,connection)
   try:yield session
   finally:session.close()
 def initialize(self):return self.backend.initialize()
 @property
 def ph(self):return self.dialect.placeholder
 def _instance(self,instance_id):
  with self.session() as s:row=s.execute(f"SELECT id,name,game_id,runtime_id,agent_id,customer_id FROM instances WHERE id={self.ph}",(str(instance_id),)).fetchone()
  return dict(row) if row else None
 def get(self,vault_id):
  with self.session() as s:row=s.execute(f"SELECT * FROM deleted_instance_backups WHERE vault_id={self.ph}",(str(vault_id),)).fetchone()
  if row is None:raise KeyError(vault_id)
  value=dict(row);raw=value.get("manifest_json")
  if isinstance(raw,str):
   try:value["manifest"]=json.loads(raw)
   except Exception:value["manifest"]={}
  elif isinstance(raw,dict):value["manifest"]=dict(raw)
  else:value["manifest"]={}
  return value
 def _set(self,vault_id,**changes):
  if not changes:return self.get(vault_id)
  changes["updated_at"]=_iso(_now());columns=list(changes);values=[changes[k] for k in columns]
  with self.session(transaction=True) as s:s.execute("UPDATE deleted_instance_backups SET "+",".join(f"{k}={self.ph}" for k in columns)+f" WHERE vault_id={self.ph}",(*values,str(vault_id)))
  return self.get(vault_id)
 def start(self,instance_id,*,requested_by,retention_hours=168):
  self.initialize();instance=self._instance(instance_id)
  if instance is None:raise KeyError(instance_id)
  if instance.get("customer_id") is None:raise ValueError("instance has no Customer owner")
  with self.session() as s:row=s.execute(f"SELECT vault_id FROM deleted_instance_backups WHERE source_instance_id={self.ph} AND status IN ('backup_pending','export_pending','removal_pending') ORDER BY created_at DESC LIMIT 1",(str(instance_id),)).fetchone()
  if row is not None:return self.get(str(row["vault_id"])),True
  job=self.backups.request(str(instance_id),action="create",reason="final_delete",requested_by=str(requested_by or "customer"));vault_id="vault-"+uuid.uuid4().hex;now=_now();expires=_iso(now+timedelta(hours=max(1,min(int(retention_hours),168))));manifest={"schema_version":1,"kind":"CapivaraDeletedInstanceBackup","source_instance_id":str(instance["id"]),"source_instance_name":instance.get("name"),"game_id":instance.get("game_id"),"runtime_id":instance.get("runtime_id")}
  with self.session(transaction=True) as s:s.execute("INSERT INTO deleted_instance_backups(vault_id,customer_id,source_instance_id,source_instance_name,game_id,runtime_id,agent_id,backup_job_id,status,manifest_json,requested_by,created_at,expires_at,updated_at) "+f"VALUES ({self.dialect.parameters(14)})",(vault_id,int(instance["customer_id"]),str(instance["id"]),instance.get("name"),str(instance.get("game_id") or ""),instance.get("runtime_id"),str(instance.get("agent_id") or ""),str(job["command_id"]),"backup_pending",json.dumps(manifest,separators=(",",":")),str(requested_by or ""),_iso(now),expires,_iso(now)))
  return self.get(vault_id),False
 def reconcile(self,vault_id):
  item=self.get(vault_id);status=str(item.get("status") or "")
  if status in {"expired","failed","ready","deleted"}:return item
  if status=="backup_pending":
   job=self.backups.get_job(str(item.get("backup_job_id") or ""))
   if not job:return self._set(vault_id,status="failed",last_error="final backup job disappeared")
   job_status=str(job.get("status") or "")
   if job_status=="failed":return self._set(vault_id,status="failed",last_error=str(job.get("last_error") or "final backup failed")[:1024])
   if job_status!="completed" or not job.get("backup_id"):return item
   filename=Path(str(job.get("artifact_path") or f"{job['backup_id']}.tar.gz")).name;transfer=self.artifacts.create(agent_id=str(item["agent_id"]),instance_id=str(item["source_instance_id"]),customer_id=int(item["customer_id"]),direction="agent_to_controller",purpose="deleted_backup_export",filename=filename,source_ref=str(job["backup_id"]),requested_by=str(item.get("requested_by") or ""),ttl_hours=168);item=self._set(vault_id,status="export_pending",backup_id=str(job["backup_id"]),transfer_id=str(transfer["transfer_id"]));status="export_pending"
  if status=="export_pending":
   transfer=self.artifacts.get(str(item.get("transfer_id") or ""));transfer_status=str(transfer.get("status") or "")
   if transfer_status=="failed":return self._set(vault_id,status="failed",last_error=str(transfer.get("last_error") or "backup export failed")[:1024])
   if transfer_status!="completed":return item
   artifact,_=self.artifacts.controller_artifact(str(transfer["transfer_id"]));remove=self.runtime.enqueue(agent_id=str(item["agent_id"]),instance_id=str(item["source_instance_id"]),action="remove",requested_by=str(item.get("requested_by") or ""));item=self._set(vault_id,status="removal_pending",artifact_path=str(artifact),size_bytes=transfer.get("size_bytes"),sha256=transfer.get("sha256"),remove_command_id=str(remove["command_id"]));status="removal_pending"
  if status=="removal_pending":
   if self._instance(str(item["source_instance_id"])) is None:return self._set(vault_id,status="ready",deleted_at=_iso(_now()))
   command_id=str(item.get("remove_command_id") or "")
   if command_id:
    try:command=self.runtime.snapshot(command_id)
    except KeyError:command=None
    if command and str(command.get("status") or "")=="failed":return self._set(vault_id,status="removal_failed",last_error=str(command.get("last_error") or "Agent could not remove instance")[:1024])
  return item
 def list_for_customer(self,customer_id):
  self.cleanup_expired();cid=int(customer_id)
  with self.session() as s:rows=s.execute(f"SELECT vault_id FROM deleted_instance_backups WHERE customer_id={self.ph} AND status NOT IN ('deleted','expired') ORDER BY created_at DESC",(cid,)).fetchall()
  output=[]
  for row in rows:
   try:output.append(self.reconcile(str(row["vault_id"])))
   except (KeyError,ValueError,PermissionError,OSError):output.append(self.get(str(row["vault_id"])))
  return output
 def artifact_for_customer(self,vault_id,customer_id):
  item=self.reconcile(vault_id)
  if int(item.get("customer_id") or 0)!=int(customer_id):raise PermissionError("backup belongs to another Customer")
  if str(item.get("status") or "")!="ready":raise FileNotFoundError("deleted instance backup is not ready")
  path=Path(str(item.get("artifact_path") or "")).resolve();path.relative_to(self.artifacts.spool)
  if not path.is_file() or path.is_symlink():raise FileNotFoundError("deleted instance backup artifact not found")
  return path,item
 def complete_download(self,vault_id,customer_id):
  _,item=self.artifact_for_customer(vault_id,customer_id);return self._set(vault_id,downloaded_at=_iso(_now()))
 def delete_for_customer(self,vault_id,customer_id):
  item=self.get(vault_id)
  if int(item.get("customer_id") or 0)!=int(customer_id):raise PermissionError("backup belongs to another Customer")
  if str(item.get("status") or "") in ACTIVE:raise ValueError("backup is still being prepared")
  path_value=str(item.get("artifact_path") or "").strip()
  if path_value:
   path=Path(path_value).resolve();path.relative_to(self.artifacts.spool);path.unlink(missing_ok=True)
   try:path.parent.rmdir()
   except OSError:pass
  return self._set(vault_id,status="deleted",artifact_path=None)
 def cleanup_expired(self):
  now=_now();count=0
  with self.session() as s:rows=s.execute("SELECT vault_id,artifact_path,expires_at FROM deleted_instance_backups WHERE status NOT IN ('deleted','expired') AND expires_at IS NOT NULL").fetchall()
  for row in rows:
   try:expires=datetime.fromisoformat(str(row["expires_at"]).replace("Z","+00:00"))
   except Exception:continue
   if expires.tzinfo is None:expires=expires.replace(tzinfo=timezone.utc)
   if expires.astimezone(timezone.utc)>now:continue
   try:
    path=Path(str(row["artifact_path"] or "")).resolve();path.relative_to(self.artifacts.spool);path.unlink(missing_ok=True)
   except (OSError,ValueError):pass
   self._set(str(row["vault_id"]),status="expired",artifact_path=None);count+=1
  return count
__all__=["ACTIVE","FINAL","DeletedBackupVaultRepository"]
