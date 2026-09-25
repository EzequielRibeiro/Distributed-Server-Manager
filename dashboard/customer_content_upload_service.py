#!/usr/bin/env python3
"""Customer external-upload bridge into Universal Content and Artifact Transfer."""
from __future__ import annotations
import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from artifact_transfer_repository import ArtifactTransferRepository
from content_repository import ContentRepository
from customer_instance_workspace_service import CustomerInstanceWorkspaceService
from minecraft_content_resolver import provider_loaders
from runtime_workspace_catalog import runtime_definition

_ALLOWED_FIELDS=frozenset({"content_id","content_type","activation_state","activation_order","version","metadata","dependencies","conflicts"})
_ARCHIVE_SUFFIXES=(".zip",".mrpack",".tar",".tar.gz",".tgz")
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
 def cancel(self,user,transfer_id):
  item=self._transfer(user,transfer_id)
  if str(item.get("status") or "").lower()=="completed":raise ValueError("content upload is already completed")
  return self.transfers.cancel(str(item["transfer_id"]))
 def _minecraft_mrpack_bundle(self,context,item,content_id,relative,metadata):
  if str(context.get("game_id") or "").strip().lower()!="minecraft":raise ValueError(".mrpack upload is available only for Minecraft")
  runtime_id=str(context.get("runtime_id") or "").strip();game_version=str(context.get("game_version") or "").strip()
  definition=runtime_definition(self.root,"minecraft",runtime_id)
  if not runtime_id or not game_version or not definition:raise ValueError("Minecraft runtime/version identity is unavailable")
  path,_=self.transfers.controller_artifact(str(item["transfer_id"]))
  try:
   with zipfile.ZipFile(path) as archive:
    try:info=archive.getinfo("modrinth.index.json")
    except KeyError as exc:raise ValueError("O arquivo .mrpack não contém modrinth.index.json.") from exc
    if info.file_size>16*1024*1024:raise ValueError("Manifesto .mrpack excede o limite de segurança.")
    try:index=json.loads(archive.read(info).decode("utf-8"))
    except (UnicodeDecodeError,json.JSONDecodeError) as exc:raise ValueError("Manifesto .mrpack inválido.") from exc
    names={entry.filename.split("/",1)[0] for entry in archive.infolist() if "/" in entry.filename}
  except zipfile.BadZipFile as exc:raise ValueError("O arquivo .mrpack não é um ZIP válido.") from exc
  if not isinstance(index,Mapping) or int(index.get("formatVersion") or 0)!=1 or str(index.get("game") or "").lower()!="minecraft":raise ValueError("Formato .mrpack não suportado.")
  deps=index.get("dependencies") if isinstance(index.get("dependencies"),Mapping) else {}
  if str(deps.get("minecraft") or "")!=game_version:raise ValueError(f"O modpack exige Minecraft {deps.get('minecraft')}; a instância usa {game_version}.")
  loaders=provider_loaders(definition,"mod")
  if len(loaders)!=1:raise ValueError("O loader do runtime Minecraft é ambíguo para importação de modpack.")
  loader=loaders[0];dep_key={"fabric":"fabric-loader","forge":"forge","neoforge":"neoforge","quilt":"quilt-loader"}.get(loader)
  loader_version=str(deps.get(dep_key) or "").strip() if dep_key else ""
  if not loader_version:raise ValueError(f"O .mrpack não declara o loader {loader} exigido pela instância.")
  members=[];children=[]
  for entry in index.get("files") or []:
   if not isinstance(entry,Mapping):raise ValueError("Entrada inválida no manifesto .mrpack.")
   env=entry.get("env") if isinstance(entry.get("env"),Mapping) else {};server=str(env.get("server") or "required").lower()
   if server in {"unsupported","optional"}:continue
   if server!="required":raise ValueError("Flag de ambiente server inválida no .mrpack.")
   member_path=str(entry.get("path") or "").strip().replace("\\","/")
   if not member_path.startswith("mods/") or not member_path.lower().endswith(".jar") or ".." in member_path.split("/"):raise ValueError("O .mrpack contém arquivo obrigatório fora de mods/.")
   hashes=entry.get("hashes") if isinstance(entry.get("hashes"),Mapping) else {};sha512=str(hashes.get("sha512") or "").lower();sha1=str(hashes.get("sha1") or "").lower()
   if len(sha512)!=128 or len(sha1)!=40:raise ValueError("Componente .mrpack sem hashes SHA-512/SHA-1 válidos.")
   urls=[str(v).strip() for v in (entry.get("downloads") or []) if str(v).strip()]
   url=next((v for v in urls if urlparse(v).scheme=="https" and urlparse(v).hostname),None)
   if not url:raise ValueError("Componente .mrpack sem URL HTTPS.")
   cid="mb-"+hashlib.sha256((content_id+"\0"+member_path).encode()).hexdigest()[:32]
   artifact={"provider":"modrinth","package_id":f"upload:{cid}","url":url,"filename":Path(member_path).name,"sha512":sha512,"sha1":sha1}
   if entry.get("fileSize") is not None:artifact["size_bytes"]=int(entry["fileSize"])
   members.append({"content_id":cid,"path":member_path,"required":True,"artifact":artifact})
   children.append({"content_id":cid,"content_type":"mod","provider":"modrinth","version":"imported","artifact":artifact,"target":f"mods/{cid}","provenance":{"bundle_provider":"modrinth","bundle_import":"external-upload","bundle_path":member_path}})
  if not members:raise ValueError("O .mrpack não contém mods obrigatórios para o servidor.")
  version_id=str(index.get("versionId") or hashlib.sha256(json.dumps(index,sort_keys=True).encode()).hexdigest()[:24])
  project_id=str(index.get("name") or content_id).strip().replace(" ","-")[:191] or content_id
  parent={"instance_id":str(context.get("id") or item.get("instance_id") or ""),"content_id":content_id,"content_type":"modpack","provider":"modrinth","version":version_id,"desired_state":"installed","activation_state":"enabled","target":f"modpacks/{content_id}","artifact":{"provider":"modrinth","package_id":f"upload:{content_id}","resolved_path":relative,"sha256":str(item.get("sha256") or "") or None,"archive":True,"filename":str(item.get("filename") or "")},"provenance":{"kind":"customer-mrpack-upload","transfer_id":str(item["transfer_id"]),"filename":str(item.get("filename") or ""), "agent_validated":True},"metadata":dict(metadata)}
  parent["metadata"]["display_name"]=str(index.get("name") or parent["metadata"].get("display_name") or content_id)
  bundle={"provider":"modrinth","provider_project_id":project_id,"provider_version_id":version_id,"minecraft_version":game_version,"loader_id":loader,"loader_version":loader_version,"manifest_kind":"mrpack-v1","members":members,"override_roots":[root for root in ("overrides","server-overrides") if root in names]}
  for child in children:child["instance_id"]=parent["instance_id"]
  return parent,bundle,children

 def _detect_curseforge_export(self,item):
  try:path,_=self.transfers.controller_artifact(str(item["transfer_id"]))
  except (AttributeError,FileNotFoundError):return False
  try:
   with zipfile.ZipFile(path) as archive:
    if "manifest.json" not in archive.namelist():return False
    info=archive.getinfo("manifest.json")
    if info.file_size>16*1024*1024:return False
    manifest=json.loads(archive.read(info).decode("utf-8"))
  except (zipfile.BadZipFile,KeyError,UnicodeDecodeError,json.JSONDecodeError,OSError):return False
  return isinstance(manifest,Mapping) and str(manifest.get("manifestType") or "")=="minecraftModpack"

 def _finalize(self,user,transfer_id,body:Mapping[str,Any],extra_assignments=None):
  item=self._transfer(user,transfer_id)
  if str(item.get("status") or "")!="completed":raise ValueError("content upload has not reached the Agent")
  iid=str(item["instance_id"]);context,effective,_=self._access(user,iid)
  if not isinstance(body,Mapping):raise ValueError("content payload must be an object")
  unknown=sorted(set(body)-_ALLOWED_FIELDS-{"instance_id","transfer_id","action"})
  if unknown:raise ValueError("unsupported content fields: "+", ".join(unknown))
  content_id=str(body.get("content_id") or "").strip()
  if not content_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-" for c in content_id):raise ValueError("Identificador inválido. Use apenas letras, números, ponto, sublinhado, dois-pontos ou hífen; a interface converte nomes amigáveis para um ID seguro.")
  ctype=str(body.get("content_type") or "other").strip().lower()
  if ctype=="plugin" and not effective.plugins_allowed:raise PermissionError("plugins are not allowed by this contract")
  if ctype=="modpack" and not effective.modpacks_allowed:raise PermissionError("modpacks are not allowed by this contract")
  if ctype=="datapack" and not effective.datapacks_allowed:raise PermissionError("datapacks are not allowed by this contract")
  if ctype in {"mod","map"} and not effective.mods_allowed:raise PermissionError("mods are not allowed by this contract")
  if ctype=="workshop":raise ValueError("external uploads cannot impersonate Steam Workshop content")
  name=self._filename(item.get("filename"));tid=str(item["transfer_id"]);relative=str(item.get("destination_ref") or "").strip().replace("\\","/")
  expected=(Path("quarantine")/iid/tid/name).as_posix()
  if relative!=expected:raise ValueError("content upload Agent quarantine acknowledgement is missing")
  lower=name.lower();archive=lower.endswith(_ARCHIVE_SUFFIXES)
  metadata=body.get("metadata") if isinstance(body.get("metadata"),Mapping) else {}
  if ctype=="modpack":
   if lower.endswith(".mrpack"):
    parent,bundle,children=self._minecraft_mrpack_bundle(context,item,content_id,relative,metadata)
    return self.content.put_bundle(parent,bundle,children,requested_by=str(user.get("username") or "customer"))
   if lower.endswith(".zip") and self._detect_curseforge_export(item):
    raise ValueError("Pacote CurseForge detectado. Esse formato referencia IDs do CurseForge e não contém URLs suficientes para instalação sem uma 3rd Party API Key. Use o equivalente .mrpack/Modrinth ou configure a chave CurseForge no Controller.")
   raise ValueError("Upload de modpack suporta .mrpack. ZIP CurseForge requer 3rd Party API Key.")
  payload={key:body[key] for key in _ALLOWED_FIELDS if key in body and key not in {"metadata"}}
  payload.update({"instance_id":iid,"content_id":content_id,"content_type":ctype,"desired_state":"installed","provider":"local","target":f"external/{content_id}","artifact":{"provider":"local","package_id":relative,"sha256":str(item.get("sha256") or "") or None,"archive":archive,"filename":name,"ephemeral_upload":True},"provenance":{"kind":"customer-upload","transfer_id":tid,"filename":name,"sha256":str(item.get("sha256") or "") or None,"quarantine_path":relative,"agent_validated":True},"metadata":dict(metadata)})
  actor=str(user.get("username") or "customer")
  extras=[dict(value) for value in (extra_assignments or []) if isinstance(value,Mapping)]
  if extras:
   result=self.content.put_many([*extras,payload],requested_by=actor)
   result["assignment"]=next(item for item in result["assignments"] if str(item.get("content_id") or "")==content_id)
   result["dependencies"]=[item for item in result["assignments"] if str(item.get("content_id") or "")!=content_id]
   return result
  return self.content.put(payload,requested_by=actor)

 def finalize_dayz_community_map(self,user,transfer_id,body:Mapping[str,Any],dependency_assignments):
  item=self._transfer(user,transfer_id)
  try:
   if not isinstance(body,Mapping):raise ValueError("content payload must be an object")
   payload=dict(body);payload["content_type"]="map";payload["activation_state"]="enabled"
   payload["dependencies"]=[str(value.get("content_id") or "").strip() for value in (dependency_assignments or []) if isinstance(value,Mapping) and str(value.get("content_id") or "").strip()]
   return self._finalize(user,transfer_id,payload,extra_assignments=dependency_assignments)
  except Exception as exc:
   if str(item.get("status") or "").lower()=="completed":
    try:self.transfers.reject_content_upload(str(item["transfer_id"]),str(exc))
    except Exception:pass
   raise

 def finalize(self,user,transfer_id,body:Mapping[str,Any]):
  item=self._transfer(user,transfer_id)
  try:
   return self._finalize(user,transfer_id,body)
  except Exception as exc:
   if str(item.get("status") or "").lower()=="completed":
    try:self.transfers.reject_content_upload(str(item["transfer_id"]),str(exc))
    except Exception:pass
   raise

__all__=["CustomerContentUploadService"]
