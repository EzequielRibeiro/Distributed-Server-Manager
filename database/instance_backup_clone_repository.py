#!/usr/bin/env python3
"""Durable orchestration for creating an Agent-owned instance from a retained backup."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime,timezone
from pathlib import Path
import uuid
from alert_repository import AlertSession,dialect_for_backend
from agent_instance_provisioning_repository import AgentInstanceProvisioningRepository
from artifact_transfer_repository import ArtifactTransferRepository
from backup_repository import BackupRepository
from deleted_backup_vault_repository import DeletedBackupVaultRepository
FINAL={"completed","failed"}
def _now_dt():return datetime.now(timezone.utc)
def _now():return _now_dt().isoformat().replace("+00:00","Z")
def _dt(value):
 try:parsed=datetime.fromisoformat(str(value).replace("Z","+00:00"))
 except Exception:return None
 if parsed.tzinfo is None:parsed=parsed.replace(tzinfo=timezone.utc)
 return parsed.astimezone(timezone.utc)
class InstanceBackupCloneRepository:
 def __init__(self,backend,root:Path):
  self.backend=backend;self.root=Path(root).resolve();self.dialect=dialect_for_backend(backend);self.provisioning=AgentInstanceProvisioningRepository(backend);self.artifacts=ArtifactTransferRepository(backend,self.root);self.backups=BackupRepository(backend);self.vault=DeletedBackupVaultRepository(backend,self.root)
 @contextmanager
 def session(self,transaction=False):
  context=self.backend.transaction() if transaction else self.backend.connect()
  with context as connection:
   session=AlertSession(self.backend,connection)
   try:yield session
   finally:session.close()
 @property
 def ph(self):return self.dialect.placeholder
 def initialize(self):return self.backend.initialize()
 def get(self,clone_id):
  with self.session() as s:row=s.execute(f"SELECT * FROM instance_backup_clones WHERE clone_id={self.ph}",(str(clone_id),)).fetchone()
  if row is None:raise KeyError(clone_id)
  return dict(row)
 def for_instance(self,instance_id):
  with self.session() as s:row=s.execute(f"SELECT clone_id FROM instance_backup_clones WHERE target_instance_id={self.ph}",(str(instance_id),)).fetchone()
  return self.get(str(row["clone_id"])) if row else None
 def list_for_customer(self,customer_id,limit=100):
  with self.session() as s:rows=s.execute(f"SELECT clone_id FROM instance_backup_clones WHERE customer_id={self.ph} ORDER BY created_at DESC LIMIT {self.ph}",(int(customer_id),max(1,min(int(limit),500)))).fetchall()
  return [self.get(str(row["clone_id"])) for row in rows]
 def _set(self,clone_id,**changes):
  if not changes:return self.get(clone_id)
  changes["updated_at"]=_now();columns=list(changes);values=[changes[k] for k in columns]
  with self.session(transaction=True) as s:s.execute("UPDATE instance_backup_clones SET "+",".join(f"{column}={self.ph}" for column in columns)+f" WHERE clone_id={self.ph}",(*values,str(clone_id)))
  return self.get(clone_id)
 def validate_source(self,vault_id,customer_id,game_id,runtime_id):
  self.vault.cleanup_expired();source=self.vault.get(str(vault_id))
  if int(source.get("customer_id") or 0)!=int(customer_id):raise PermissionError("backup vault belongs to another Customer")
  if str(source.get("status") or "")!="ready":raise ValueError("backup vault is not ready")
  expires=_dt(source.get("expires_at"))
  if expires is not None and expires<=_now_dt():raise ValueError("backup vault has expired")
  if str(source.get("game_id") or "")!=str(game_id):raise ValueError("backup game does not match requested game")
  source_runtime=str(source.get("runtime_id") or "").strip();target_runtime=str(runtime_id or "").strip()
  if source_runtime and target_runtime and source_runtime!=target_runtime:raise ValueError("backup runtime does not match requested runtime")
  path=Path(str(source.get("artifact_path") or "")).resolve();path.relative_to(self.artifacts.spool)
  if not path.is_file() or path.is_symlink():raise FileNotFoundError("backup vault artifact is missing")
  return source,path
 def start(self,*,customer_id,source_vault_id,target_instance_id,target_agent_id,provisioning_id,requested_by):
  self.initialize();existing=self.for_instance(target_instance_id)
  if existing:return existing,True
  clone_id="clone-"+uuid.uuid4().hex;now=_now()
  with self.session(transaction=True) as s:s.execute("INSERT INTO instance_backup_clones(clone_id,customer_id,source_vault_id,target_instance_id,target_agent_id,provisioning_id,status,requested_by,created_at,updated_at) "+f"VALUES ({self.dialect.parameters(10)})",(clone_id,int(customer_id),str(source_vault_id),str(target_instance_id),str(target_agent_id),str(provisioning_id),"provisioning",str(requested_by or "") or None,now,now))
  return self.get(clone_id),False
 def reconcile(self,clone_id):
  item=self.get(clone_id);status=str(item.get("status") or "")
  if status in FINAL:return item
  if status=="provisioning":
   provision=self.provisioning.snapshot(str(item["provisioning_id"]));state=str(provision.get("status") or "")
   if state=="failed":return self._set(clone_id,status="failed",last_error=str(provision.get("last_error") or "target provisioning failed")[:1024])
   if state!="completed":return item
   _,path=self.validate_source(item["source_vault_id"],item["customer_id"],self._target_game(item["target_instance_id"]),self._target_runtime(item["target_instance_id"]))
   imported="clone-"+uuid.uuid4().hex;transfer=self.artifacts.create(agent_id=str(item["target_agent_id"]),instance_id=str(item["target_instance_id"]),customer_id=int(item["customer_id"]),direction="controller_to_agent",purpose="backup_clone",filename=path.name,destination_ref=imported,requested_by=str(item.get("requested_by") or ""),ttl_hours=24)
   with path.open("rb") as source_stream:self.artifacts.stage_from_controller(str(transfer["transfer_id"]),source_stream,path.stat().st_size)
   item=self._set(clone_id,status="transferring",transfer_id=str(transfer["transfer_id"]),imported_backup_id=imported);status="transferring"
  if status=="transferring":
   transfer=self.artifacts.get(str(item.get("transfer_id") or ""));state=str(transfer.get("status") or "")
   if state in {"failed","expired","cancelled"}:return self._set(clone_id,status="failed",last_error=str(transfer.get("last_error") or f"backup transfer {state}")[:1024])
   if state!="completed":return item
   existing=next((job for job in self.backups.list_jobs(instance_id=str(item["target_instance_id"]),limit=200) if job.get("action")=="restore" and str(job.get("backup_id") or "")==str(item["imported_backup_id"]) and str(job.get("status") or "") in {"pending","running","completed"}),None)
   job=existing or self.backups.request(str(item["target_instance_id"]),action="restore",backup_id=str(item["imported_backup_id"]),reason="create_from_backup",requested_by=str(item.get("requested_by") or ""));item=self._set(clone_id,status="restoring",restore_job_id=str(job["command_id"]));status="restoring"
  if status=="restoring":
   job=self.backups.get_job(str(item.get("restore_job_id") or ""))
   if not job:return self._set(clone_id,status="failed",last_error="restore job disappeared")
   state=str(job.get("status") or "")
   if state=="failed":return self._set(clone_id,status="failed",last_error=str(job.get("last_error") or "backup restore failed")[:1024])
   if state=="completed":return self._set(clone_id,status="completed",completed_at=_now(),last_error=None)
  return item
 def _target(self,instance_id):
  with self.session() as s:row=s.execute(f"SELECT game_id,runtime_id FROM instances WHERE id={self.ph}",(str(instance_id),)).fetchone()
  if row is None:raise KeyError(instance_id)
  return dict(row)
 def _target_game(self,instance_id):return str(self._target(instance_id).get("game_id") or "")
 def _target_runtime(self,instance_id):return str(self._target(instance_id).get("runtime_id") or "")
 def list_active(self,agent_id=None):
  where="status NOT IN ('completed','failed')";params=[]
  if agent_id is not None:where+=f" AND target_agent_id={self.ph}";params.append(str(agent_id))
  with self.session() as s:rows=s.execute(f"SELECT clone_id FROM instance_backup_clones WHERE {where} ORDER BY created_at",tuple(params)).fetchall()
  return [self.get(str(row["clone_id"])) for row in rows]
 def reconcile_for_agent(self,agent_id):
  result=[]
  for item in self.list_active(agent_id):
   try:result.append(self.reconcile(str(item["clone_id"])))
   except Exception as exc:result.append(self._set(str(item["clone_id"]),status="failed",last_error=str(exc)[:1024]))
  return result
__all__=["FINAL","InstanceBackupCloneRepository"]
