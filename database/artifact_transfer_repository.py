#!/usr/bin/env python3
"""Persistence for large artifacts exchanged through outbound-only Agents."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
import hashlib,os
from pathlib import Path
import uuid
from alert_repository import AlertSession,dialect_for_backend

FINAL={"completed","failed","cancelled","expired"};ACTIVE={"queued","delivered","transferring"}
class ArtifactTransferRepository:
 def __init__(self,backend,root:Path):
  self.backend=backend;self.dialect=dialect_for_backend(backend);candidate=Path(root)
  if str(candidate) in {"","."}:candidate=Path(__file__).resolve().parents[1]
  self.root=candidate.resolve();self.spool=(self.root/"runtime"/"artifact-transfers").resolve();self.spool.relative_to(self.root)
 @contextmanager
 def session(self,transaction=False):
  context=self.backend.transaction() if transaction else self.backend.connect()
  with context as c:
   s=AlertSession(self.backend,c)
   try:yield s
   finally:s.close()
 def initialize(self):return self.backend.initialize()
 @staticmethod
 def _token(value,label):
  text=str(value or "").strip()
  if not text or len(text)>191 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for c in text):raise ValueError(f"invalid {label}")
  return text
 def _path(self,transfer_id,filename):
  transfer=self._token(transfer_id,"transfer_id");name=Path(str(filename or "artifact.bin")).name
  if not name or name in {".",".."}:raise ValueError("invalid artifact filename")
  directory=(self.spool/transfer).resolve();directory.relative_to(self.spool);return directory/name
 def create(self,*,agent_id,instance_id=None,customer_id=None,direction,purpose,filename,source_ref=None,destination_ref=None,requested_by=None,ttl_hours=24):
  if direction not in {"agent_to_controller","controller_to_agent"}:raise ValueError("invalid transfer direction")
  transfer_id="transfer-"+uuid.uuid4().hex;filename=Path(str(filename or "artifact.bin")).name;expires=(datetime.now(timezone.utc)+timedelta(hours=max(1,min(int(ttl_hours),168)))).isoformat().replace("+00:00","Z");path=self._path(transfer_id,filename)
  self.initialize()
  with self.session(transaction=True) as s:s.execute("INSERT INTO artifact_transfers(transfer_id,agent_id,instance_id,customer_id,direction,purpose,source_ref,destination_ref,filename,status,controller_path,requested_by,expires_at) "+f"VALUES ({self.dialect.parameters(13)})",(transfer_id,str(agent_id),str(instance_id) if instance_id else None,int(customer_id) if customer_id is not None else None,direction,str(purpose),str(source_ref) if source_ref else None,str(destination_ref) if destination_ref else None,filename,"queued",str(path),str(requested_by or "") or None,expires))
  return self.get(transfer_id)
 def get(self,transfer_id):
  ph=self.dialect.placeholder
  with self.session() as s:row=s.execute(f"SELECT * FROM artifact_transfers WHERE transfer_id={ph}",(str(transfer_id),)).fetchone()
  if row is None:raise KeyError(transfer_id)
  return dict(row)
 def command_for_agent(self,agent_id):
  ph=self.dialect.placeholder
  with self.session(transaction=True) as s:
   row=s.execute(f"SELECT transfer_id FROM artifact_transfers WHERE agent_id={ph} AND status='queued' ORDER BY created_at ASC LIMIT 1",(str(agent_id),)).fetchone()
   if row is None:return None
   tid=str(row["transfer_id"]);s.execute(f"UPDATE artifact_transfers SET status='delivered',delivered_at={self.dialect.current_timestamp},updated_at={self.dialect.current_timestamp} WHERE transfer_id={ph} AND status='queued'",(tid,))
  item=self.get(tid);return {k:item.get(k) for k in ("transfer_id","direction","purpose","instance_id","source_ref","destination_ref","filename","size_bytes","sha256")}
 def mark_transferring(self,transfer_id):
  ph=self.dialect.placeholder
  with self.session(transaction=True) as s:s.execute(f"UPDATE artifact_transfers SET status='transferring',updated_at={self.dialect.current_timestamp} WHERE transfer_id={ph} AND status IN ('queued','delivered','transferring')",(transfer_id,))
  return self.get(transfer_id)
 def receive_from_agent(self,transfer_id,agent_id,source,content_length=None):
  item=self.get(transfer_id)
  if item["direction"]!="agent_to_controller" or str(item["agent_id"])!=str(agent_id):raise PermissionError("artifact transfer ownership mismatch")
  if str(item["status"]) in FINAL:raise ValueError("artifact transfer is already final")
  path=self._path(transfer_id,item["filename"]);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(path.suffix+".part");h=hashlib.sha256();total=0
  try:
   with tmp.open("wb") as out:
    while True:
     chunk=source.read(1024*1024)
     if not chunk:break
     total+=len(chunk)
     if total>64*1024*1024*1024:raise ValueError("artifact exceeds 64 GiB transfer limit")
     h.update(chunk);out.write(chunk)
   if content_length is not None and total!=int(content_length):raise ValueError("artifact content length mismatch")
   os.replace(tmp,path)
  finally:
   try:tmp.unlink()
   except FileNotFoundError:pass
  ph=self.dialect.placeholder;digest=h.hexdigest()
  with self.session(transaction=True) as s:s.execute(f"UPDATE artifact_transfers SET status='completed',size_bytes={ph},transferred_bytes={ph},sha256={ph},controller_path={ph},completed_at={self.dialect.current_timestamp},updated_at={self.dialect.current_timestamp} WHERE transfer_id={ph}",(total,total,digest,str(path),transfer_id))
  return self.get(transfer_id)
 def stage_from_controller(self,transfer_id,source,content_length=None):
  item=self.get(transfer_id)
  if item["direction"]!="controller_to_agent":raise ValueError("transfer direction does not accept Controller upload")
  path=self._path(transfer_id,item["filename"]);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(path.suffix+".part");h=hashlib.sha256();total=0
  try:
   with tmp.open("wb") as out:
    while True:
     chunk=source.read(1024*1024)
     if not chunk:break
     total+=len(chunk)
     if total>64*1024*1024*1024:raise ValueError("artifact exceeds 64 GiB transfer limit")
     h.update(chunk);out.write(chunk)
   if content_length is not None and total!=int(content_length):raise ValueError("artifact content length mismatch")
   os.replace(tmp,path)
  finally:
   try:tmp.unlink()
   except FileNotFoundError:pass
  ph=self.dialect.placeholder;digest=h.hexdigest()
  with self.session(transaction=True) as s:s.execute(f"UPDATE artifact_transfers SET size_bytes={ph},transferred_bytes=0,sha256={ph},controller_path={ph},status='queued',updated_at={self.dialect.current_timestamp} WHERE transfer_id={ph}",(total,digest,str(path),transfer_id))
  return self.get(transfer_id)
 def controller_artifact(self,transfer_id):
  item=self.get(transfer_id);path=Path(str(item.get("controller_path") or "")).resolve();path.relative_to(self.spool)
  if not path.is_file() or path.is_symlink():raise FileNotFoundError("artifact is not ready")
  return path,item
 def apply_agent_result(self,agent_id,report):
  if not isinstance(report,dict) or not report.get("transfer_id"):return None
  item=self.get(str(report["transfer_id"]))
  if str(item["agent_id"])!=str(agent_id):raise PermissionError("artifact transfer belongs to another Agent")
  status=str(report.get("status") or "").lower()
  if status not in {"completed","failed"}:raise ValueError("invalid transfer result status")
  ph=self.dialect.placeholder
  with self.session(transaction=True) as s:s.execute(f"UPDATE artifact_transfers SET status={ph},transferred_bytes={ph},last_error={ph},completed_at={self.dialect.current_timestamp},updated_at={self.dialect.current_timestamp} WHERE transfer_id={ph}",(status,int(report.get("transferred_bytes") or item.get("size_bytes") or 0),str(report.get("error") or "")[:1024] or None,item["transfer_id"]))
  return self.get(item["transfer_id"])
 def cleanup_expired(self):
  now=datetime.now(timezone.utc).isoformat().replace("+00:00","Z");ph=self.dialect.placeholder
  with self.session() as s:rows=s.execute(f"SELECT transfer_id,controller_path FROM artifact_transfers WHERE expires_at IS NOT NULL AND expires_at<{ph} AND status<>'expired'",(now,)).fetchall()
  count=0
  for row in rows:
   try:
    path=Path(str(row["controller_path"] or "")).resolve();path.relative_to(self.spool);path.unlink(missing_ok=True);path.parent.rmdir()
   except OSError:pass
   with self.session(transaction=True) as s:s.execute(f"UPDATE artifact_transfers SET status='expired',updated_at={self.dialect.current_timestamp} WHERE transfer_id={ph}",(str(row["transfer_id"]),))
   count+=1
  return count

__all__=["ACTIVE","FINAL","ArtifactTransferRepository"]
