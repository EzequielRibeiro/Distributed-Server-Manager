#!/usr/bin/env python3
"""Customer external-upload bridge into Universal Content and Artifact Transfer."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Mapping

from artifact_transfer_repository import ArtifactTransferRepository
from content_repository import ContentRepository
from customer_instance_workspace_service import CustomerInstanceWorkspaceService

_ALLOWED_FIELDS=frozenset({"content_id","content_type","activation_state","activation_order","version","metadata","dependencies","conflicts"})
_ARCHIVE_SUFFIXES=(".zip",".tar",".tar.gz",".tgz")
_UPLOAD_SUFFIXES=(*_ARCHIVE_SUFFIXES,".jar")

class CustomerContentUploadService:
 def __init__(self,backend,root):
  self.backend=backend;self.root=Path(root);self.workspace=CustomerInstanceWorkspaceService(backend,self.root);self.transfers=ArtifactTransferRepository(backend,self.root);self.content=ContentRepository(backend)
 def _access(self,user,instance_id):
  context=self.workspace.require(user,instance_id,"content.install");policy=self.workspace.repo.workspace_policy(instance_id);_,effective=self.workspace._contract_policy(context,policy)
  if not effective.external_upload_allowed:raise PermissionError("external content upload is not allowed by this contract")
  if not effective.modifications_allowed:raise PermissionError("managed content is not allowed by this contract")
  agent_id=str(context.get("agent_id") or "").strip()
  if not agent_id:raise ValueError("instance has no Agent")
  return context,effective,agent_id
 @staticmethod
 def _filename(value):
  raw=str(value or "").strip();name=Path(raw).name
  if not name or name in {".",".."} or name!=raw or any(c in name for c in ("\x00","\r","\n")):raise ValueError("invalid upload filename")
  if not name.lower().endswith(_UPLOAD_SUFFIXES):raise ValueError("unsupported external content artifact")
  return name[:255]
 def _transfer(self,user,transfer_id):
  item=self.transfers.get(str(transfer_id or ""));iid=str(item.get("instance_id") or "")
  if not iid or item.get("direction")!="controller_to_agent" or item.get("purpose")!="content_upload":raise ValueError("transfer is not a content upload")
  self._access(user,iid);return item
 def create(self,user,instance_id,filename):
  context,_,agent_id=self._access(user,instance_id);name=self._filename(filename)
  return self.transfers.create(agent_id=agent_id,instance_id=instance_id,customer_id=context.get("customer_id"),direction="controller_to_agent",purpose="content_upload",filename=name,requested_by=str(user.get("username") or ""),ttl_hours=24)
 def stage(self,user,transfer_id,source,content_length):
  item=self._transfer(user,transfer_id)
  if str(item.get("status") or "")!="staging":raise ValueError("content upload is not pending")
  return self.transfers.stage_from_controller(str(item["transfer_id"]),source,content_length)
 def status(self,user,transfer_id):return self._transfer(user,transfer_id)
 def finalize(self,user,transfer_id,body:Mapping[str,Any]):
  item=self._transfer(user,transfer_id)
  if str(item.get("status") or "")!="completed":raise ValueError("content upload has not reached the Agent")
  iid=str(item["instance_id"]);_,effective,_=self._access(user,iid)
  if not isinstance(body,Mapping):raise ValueError("content payload must be an object")
  unknown=sorted(set(body)-_ALLOWED_FIELDS-{"instance_id","transfer_id","action"})
  if unknown:raise ValueError("unsupported content fields: "+", ".join(unknown))
  content_id=str(body.get("content_id") or "").strip()
  if not content_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-" for c in content_id):raise ValueError("invalid content_id")
  ctype=str(body.get("content_type") or "other").strip().lower()
  if ctype=="plugin" and not effective.plugins_allowed:raise PermissionError("plugins are not allowed by this contract")
  if ctype=="modpack":
   if not effective.modpacks_allowed:raise PermissionError("modpacks are not allowed by this contract")
   raise ValueError("external modpacks require composed bundle resolution")
  if ctype=="datapack" and not effective.datapacks_allowed:raise PermissionError("datapacks are not allowed by this contract")
  if ctype in {"mod","map"} and not effective.mods_allowed:raise PermissionError("mods are not allowed by this contract")
  if ctype=="workshop":raise ValueError("external uploads cannot impersonate Steam Workshop content")
  name=self._filename(item.get("filename"));tid=str(item["transfer_id"]);relative=str(item.get("destination_ref") or "").strip().replace("\\","/")
  expected=(Path("quarantine")/iid/tid/name).as_posix()
  if relative!=expected:raise ValueError("content upload Agent quarantine acknowledgement is missing")
  lower=name.lower();archive=lower.endswith(_ARCHIVE_SUFFIXES)
  metadata=body.get("metadata") if isinstance(body.get("metadata"),Mapping) else {}
  payload={key:body[key] for key in _ALLOWED_FIELDS if key in body and key not in {"metadata"}}
  payload.update({"instance_id":iid,"content_id":content_id,"content_type":ctype,"desired_state":"installed","provider":"local","target":f"external/{content_id}","artifact":{"provider":"local","package_id":relative,"sha256":str(item.get("sha256") or "") or None,"archive":archive,"filename":name,"ephemeral_upload":True},"provenance":{"kind":"customer-upload","transfer_id":tid,"filename":name,"sha256":str(item.get("sha256") or "") or None,"quarantine_path":relative,"agent_validated":True},"metadata":dict(metadata)})
  return self.content.put(payload,requested_by=str(user.get("username") or "customer"))

__all__=["CustomerContentUploadService"]
