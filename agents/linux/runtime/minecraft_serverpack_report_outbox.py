#!/usr/bin/env python3
"""Durable Agent-owned Server Pack report outbox for authenticated heartbeat.

The saga enqueues only after committed local/source promotion. Every delivery
revalidates the active Agent records and activation checksum; controller ACK
must match before deleting the outbox entry. No retries spawn game operations.
"""
from __future__ import annotations
import json,os,re
from pathlib import Path
from typing import Any,Mapping

from minecraft_serverpack_report_delivery_payload import (
 build_committed_serverpack_report_delivery,
)

_SAFE=re.compile(r"^instance-provision-[A-Za-z0-9._-]{1,172}$")
_PATHS=("source_promotion_journal","state_promotion_journal",
        "staged_manifest","prepared_reports","active_states","active_snapshot")
_FIELDS=frozenset({"offer","agent_id",*_PATHS})


def _folder(root:Path)->Path:
 root=Path(root)
 return root/"serverpack-report-outbox"


def _atomic(path:Path,content:dict[str,Any])->None:
 tmp=path.with_name("."+path.name+".partial")
 if tmp.exists() or tmp.is_symlink():
  raise ValueError("unresolved partial outbox write")
 with tmp.open("x",encoding="utf-8") as f:
  f.write(json.dumps(content,sort_keys=True,separators=(",",":"),ensure_ascii=False)+"\n")
  f.flush();os.fsync(f.fileno())
 os.chmod(tmp,0o600)
 os.replace(tmp,path)
 fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
 try:os.fsync(fd)
 finally:os.close(fd)


def queue_serverpack_report_delivery(*,state_dir:Path,
 offer:Mapping[str,Any],agent_id:str,**paths:Any)->str:
 if set(paths)!=set(_PATHS):
  raise ValueError("missing outbox evidence paths")
 pid=offer.get("provisioning_id") if isinstance(offer,Mapping) else None
 if not isinstance(pid,str) or _SAFE.fullmatch(pid) is None:
  raise ValueError("invalid outbox provisioning id")
 record={"offer":dict(offer),"agent_id":agent_id}
 record.update({key:str(Path(paths[key]).resolve(strict=True)) for key in _PATHS})
 # Before creating an outbox entry, confirm local state really is committed.
 build_committed_serverpack_report_delivery(
  offer=record["offer"],agent_id=agent_id,
  **{key:Path(record[key]) for key in _PATHS},
 )
 root=_folder(Path(state_dir))
 if root.exists() and (not root.is_dir() or root.is_symlink()):
  raise ValueError("unsafe Agent outbox directory")
 root.mkdir(mode=0o700,parents=True,exist_ok=True)
 path=root/(pid+".json")
 if path.exists():
  if path.is_symlink() or json.loads(path.read_text(encoding="utf-8"))!=record:
   raise ValueError("conflicting outbox delivery already exists")
  return "already_queued"
 _atomic(path,record)
 return "queued"


def read_serverpack_report_delivery(state_dir:Path)->tuple[dict[str,Any],str]|None:
 root=_folder(Path(state_dir))
 if not root.is_dir() or root.is_symlink():
  return None
 pending=sorted(root.glob("instance-provision-*.json"))
 for file in pending[:16]:
  if file.is_symlink() or not file.is_file() or file.stat().st_size>4096:
   continue
  try:
   record=json.loads(file.read_text(encoding="utf-8"))
   if not isinstance(record,dict) or set(record)!=_FIELDS:
    continue
   offer=record["offer"]
   if not isinstance(offer,dict) or file.name!=str(offer.get("provisioning_id"))+".json":
    continue
   batch=build_committed_serverpack_report_delivery(
    offer=offer,agent_id=record["agent_id"],
    **{key:Path(record[key]) for key in _PATHS},
   )
   return batch,file.name
  except (OSError,ValueError,TypeError,KeyError):
   continue
 return None


def acknowledge_serverpack_report_delivery(
    state_dir:Path,filename:str,
    sent:Mapping[str,Any],response:Mapping[str,Any],
)->bool:
 if not isinstance(filename,str) or not filename.endswith(".json") or (
     _SAFE.fullmatch(filename[:-5]) is None):
  return False
 if not isinstance(sent,Mapping) or not isinstance(response,Mapping):
  return False
 if not (response.get("status")=="published"
  and response.get("provisioning_id")==sent.get("provisioning_id")
  and response.get("instance_id")==sent.get("instance_id")
  and response.get("candidate_sha256")==sent.get("candidate_sha256")
  and isinstance(response.get("bundle_revision"),int)
  and response.get("bundle_revision")>0
  and response.get("reports")==len(sent.get("reports") or [])):
  return False
 root=_folder(Path(state_dir))
 path=root/filename
 if not root.is_dir() or root.is_symlink() or not path.is_file() or path.is_symlink():
  return False
 try:
  record=json.loads(path.read_text(encoding="utf-8"))
  if not isinstance(record,dict) or (
   record.get("offer",{}).get("bundle_revision")!=response["bundle_revision"]
   or record.get("offer",{}).get("candidate_sha256")!=sent["candidate_sha256"]
   or record.get("offer",{}).get("provisioning_id")!=sent["provisioning_id"]
  ):
   return False
  path.unlink()
  fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY)
  try:os.fsync(fd)
  finally:os.close(fd)
  return True
 except (OSError,ValueError,TypeError,KeyError):
  return False
