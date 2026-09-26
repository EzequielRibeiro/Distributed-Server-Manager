#!/usr/bin/env python3
"""Customer external-upload bridge into Universal Content and Artifact Transfer."""
from __future__ import annotations
import hashlib
import ipaddress
import json
import socket
import zipfile
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from artifact_transfer_repository import ArtifactTransferRepository
from content_repository import ContentRepository
from customer_instance_workspace_service import CustomerInstanceWorkspaceService
from minecraft_content_resolver import provider_loaders
from runtime_workspace_catalog import runtime_definition
from customer_serverpack_service import build_serverpack_bundle
from customer_modpack_source_discovery import discover_modpack as detect_modpack_source

_ALLOWED_FIELDS=frozenset({"content_id","content_type","activation_state","activation_order","version","metadata","dependencies","conflicts"})
_ARCHIVE_SUFFIXES=(".zip",".mrpack",".tar",".tar.gz",".tgz")
_UPLOAD_SUFFIXES=(*_ARCHIVE_SUFFIXES,".jar")
_EXTERNAL_URL_MAX_BYTES=8*1024*1024*1024

def _safe_external_url(value, trusted_suffix=None):
 raw=str(value or "").strip();parsed=urlparse(raw)
 if parsed.scheme!="https" or not parsed.hostname or parsed.username or parsed.password:raise ValueError("external content URL must use HTTPS without embedded credentials")
 if parsed.port not in {None,443}:raise ValueError("external content URL must use the standard HTTPS port")
 host=parsed.hostname.rstrip(".").lower()
 if trusted_suffix and (host==trusted_suffix or not host.endswith("."+trusted_suffix)):
  raise ValueError("O download deve usar o CDN oficial do provedor.")
 try:addresses=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
 except socket.gaierror as exc:raise ValueError("external content URL host cannot be resolved") from exc
 if not addresses:raise ValueError("external content URL host cannot be resolved")
 for entry in addresses:
  address=ipaddress.ip_address(entry[4][0].split("%",1)[0])
  if address.is_private or address.is_loopback or address.is_link_local or address.is_multicast or address.is_reserved or address.is_unspecified:
   raise ValueError("external content URL resolves to a private or reserved address")
 return raw

class _ExternalContentRedirectHandler(HTTPRedirectHandler):
 def __init__(self,trusted_suffix=None):
  super().__init__();self.trusted_suffix=trusted_suffix
 def redirect_request(self,req,fp,code,msg,headers,newurl):
  _safe_external_url(newurl,self.trusted_suffix)
  return super().redirect_request(req,fp,code,msg,headers,newurl)

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
 def import_url(self,user,instance_id,url,*,trusted_suffix=None,filename_override=None,expected_sha1=None,max_bytes=_EXTERNAL_URL_MAX_BYTES):
  safe=_safe_external_url(url,trusted_suffix);parsed=urlparse(safe)
  name=self._filename(filename_override if filename_override else Path(parsed.path).name)
  if expected_sha1 is not None and (len(str(expected_sha1))!=40 or any(c not in "0123456789abcdef" for c in str(expected_sha1).lower())):
   raise ValueError("SHA-1 oficial inválido.")
  item=self.create(user,instance_id,name);transfer_id=str(item["transfer_id"])
  request=Request(safe,headers={"Accept":"application/octet-stream,application/zip;q=0.9,*/*;q=0.5","User-Agent":"Capivara-DSM/2"})
  # Disable environment proxies for this SSRF-sensitive fetch. Redirects are
  # revalidated and a declared Content-Length is required so the 8 GiB ceiling
  # remains fail-closed before bytes are accepted into staging.
  opener=build_opener(ProxyHandler({}),_ExternalContentRedirectHandler(trusted_suffix))
  try:
   with opener.open(request,timeout=30) as response:
    _safe_external_url(response.geturl(),trusted_suffix)
    raw_length=str(response.headers.get("Content-Length") or "").strip()
    if not raw_length:raise ValueError("external content URL must provide Content-Length")
    length=int(raw_length)
    if length<1 or length>max_bytes:raise ValueError("O arquivo excede o tamanho máximo permitido para esta importação.")
    if expected_sha1 is not None:
     # Verify the complete provider stream before queueing any Agent command.
     import tempfile
     with tempfile.SpooledTemporaryFile(max_size=16*1024*1024,mode="w+b") as verified:
      digest=hashlib.sha1();received=0
      while received<length:
       chunk=response.read(min(1024*1024,length-received))
       if not chunk:break
       received+=len(chunk)
       digest.update(chunk);verified.write(chunk)
      if received!=length or response.read(1):
       raise ValueError("O tamanho do download oficial diverge do Content-Length.")
      if digest.hexdigest()!=str(expected_sha1).lower():
       raise ValueError("O arquivo transferido não corresponde ao SHA-1 publicado pelo provedor.")
      verified.seek(0)
      staged=self.transfers.stage_from_controller(transfer_id,verified,length)
    else:
     staged=self.transfers.stage_from_controller(transfer_id,response,length)
  except Exception:
   try:self.transfers.cancel(transfer_id)
   except Exception:pass
   raise
  return staged
 def discover_provider_modpack(self,user,instance_id,body):
  if not isinstance(body,Mapping):raise ValueError("Consulta de modpack inválida.")
  # Catalog discovery is available even when the contract forbids external
  # uploads. Actual ZIP transfer still passes through _access().
  context=self.workspace.require(user,instance_id,"content.install")
  policy=self.workspace.repo.workspace_policy(instance_id)
  _,effective=self.workspace._contract_policy(context,policy)
  if (str(context.get("game_id") or "").lower()!="minecraft"
      or not effective.modifications_allowed or not effective.modpacks_allowed
      or not effective.mods_allowed):
   raise PermissionError("A instância não autoriza modpacks de Minecraft.")
  if not str(context.get("agent_id") or "").strip():
   raise ValueError("A instância ainda não possui Agent.")
  provider=str(body.get("provider") or "").strip().lower()
  project=str(body.get("project_id") or "").strip()
  version_id=str(body.get("version_id") or "").strip()
  if len(project)>80 or len(version_id)>80:
   raise ValueError("Identificador do provedor excede o limite.")
  runtime=runtime_definition(self.root,"minecraft",str(context.get("runtime_id") or ""))
  loaders=provider_loaders(runtime,"mod") if runtime else []
  version=str(context.get("game_version") or "")
  if not version or len(loaders)!=1:
   raise ValueError("Runtime Minecraft e loader devem estar definidos.")
  return detect_modpack_source(provider,project,version,loaders[0],version_id)

 def download_discovered_serverpack(self,user,instance_id,body):
  if not isinstance(body,Mapping) or body.get("provider")!="curseforge":
   raise ValueError("O download de Server Pack exige um arquivo oficial do CurseForge.")
  discovery=self.discover_provider_modpack(user,instance_id,body)
  if discovery.get("mode")!="serverpack_auto":
   raise ValueError(str(discovery.get("reason") or "O download oficial não foi autorizado."))
  chosen=str(body.get("serverpack_file_id") or "").strip()
  if chosen!=str(discovery.get("serverpack_file_id") or ""):
   raise ValueError("O Server Pack selecionado mudou; atualize a descoberta.")
  url=str(discovery["download_url"])
  item=self.import_url(user,instance_id,url,trusted_suffix="forgecdn.net",
                       filename_override=str(discovery["file_name"]),expected_sha1=str(discovery["sha1"]),
                       max_bytes=4*1024*1024*1024)
  source={k:discovery[k] for k in ("provider","project_id","serverpack_file_id","file_name","sha1","size_bytes","official_page")}
  return {"transfer":item,"source":source}

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

 def _serverpack_capacity(self,context,content_id,children):
  """Guard the per-Agent 2000-item reconciliation envelope before any DB write."""
  agent_id=str(context.get("agent_id") or "").strip()
  iid=str(context.get("id") or "").strip()
  if not agent_id or not iid:raise ValueError("Agent/instância não foi identificado.")
  existing=self.content.list(agent_id=agent_id,limit=2000)
  for assigned in existing:
   if (str(assigned.get("instance_id") or "")==iid
       and str(assigned.get("content_type") or "")=="modpack"
       and str(assigned.get("content_id") or "")!=str(content_id)
       and str(assigned.get("desired_state") or "installed")=="installed"
       and str(assigned.get("activation_state") or "enabled")=="enabled"):
    raise ValueError("Esta instância já possui um modpack ativo. Use o identificador "
                     "do modpack existente para atualizar, sem criar outra instalação.")
  if len(existing)>=2000:raise ValueError("O Agent atingiu o limite de 2000 conteúdos gerenciados.")
  identities={(str(item.get("instance_id") or ""),str(item.get("content_id") or "")) for item in existing}
  requested={(iid,str(content_id))}|{(iid,str(child["content_id"])) for child in children}
  if len(identities|requested)>2000:
   raise ValueError("O Server Pack excede a capacidade de 2000 conteúdos gerenciados deste Agent.")

 def _serverpack_revision_plan(self,context,content_id,bundle,expected_revision=None):
  """Plan a same-instance update; a new ZIP never means recreating the server."""
  iid=str(context.get("id") or "")
  history=self.content.bundle_history(iid,content_id)
  previous=history[0] if history else None
  revision=int(previous.get("revision") or 0) if previous else 0
  if previous:
   same=(str(bundle.get("provider") or "")=="local"
         and str(bundle.get("manifest_kind") or "")=="serverpack-local-v1"
         and str(previous.get("provider") or "")=="local"
         and str(previous.get("manifest_kind") or "")=="serverpack-local-v1"
         and str(previous.get("provider_project_id") or "")==str(bundle["provider_project_id"])
         and str(previous.get("minecraft_version") or "")==str(bundle["minecraft_version"])
         and str(previous.get("loader_id") or "")==str(bundle["loader_id"])
         and str(previous.get("loader_version") or "")==str(bundle["loader_version"]))
   if not same:raise ValueError(
    "Atualização recusada: o pacote alterou projeto Minecraft, formato ou NeoForge. "
    "Faça uma migração de runtime separada, com backup; a instância não será recriada.")
  if expected_revision is not None:
   if isinstance(expected_revision,bool) or str(expected_revision)!=str(revision):
    raise ValueError("A revisão do modpack mudou desde a prévia. Refaça a validação antes de atualizar.")
  diff=self.content.bundle_diff(iid,content_id,bundle) if previous else {
   "added":[str(member["content_id"]) for member in bundle.get("members") or []],
   "removed":[],"updated":[],"unchanged":[]}
  if previous and (str(previous.get("provider_version_id") or "")==
                   str(bundle["provider_version_id"])):
   if diff["added"] or diff["removed"] or diff["updated"]:
    raise ValueError("O provedor alterou o conteúdo de uma versão já publicada. "
                     "Selecione uma nova versão identificável; nenhum arquivo será substituído.")
  return {"operation":"update" if previous else "install",
          "previous_revision":revision,"manifest_diff":diff,
          "preserve_world":True,"preserve_existing_config":bool(previous),
          "requires_stopped_instance":True,
          "requires_backup_confirmation":bool(previous)}

 def preview_serverpack(self,user,transfer_id,body:Mapping[str,Any]):
  """Read-only inspection. Never changes desired content or uploads again."""
  item=self._transfer(user,transfer_id)
  if str(item.get("status") or "")!="completed":
   raise ValueError("O Server Pack ainda não chegou ao Agent.")
  context,effective,_=self._access(user,str(item["instance_id"]))
  if not effective.modpacks_allowed or not effective.mods_allowed:
   raise PermissionError("O contrato não autoriza importação de modpacks.")
  if not isinstance(body,Mapping) or set(body)-{"instance_id","transfer_id","content_id","content_type","metadata"}:
   raise ValueError("Metadados de Server Pack inválidos.")
  cid=str(body.get("content_id") or "").strip()
  if not cid or len(cid)>191 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-" for c in cid):
   raise ValueError("Identificador de Server Pack inválido.")
  filename=self._filename(item.get("filename"))
  if not filename.lower().endswith(".zip") or self._detect_curseforge_export(item):
   raise ValueError("Importe um ZIP de servidor oficial, não uma exportação CurseForge.")
  relative=str(item.get("destination_ref") or "").replace("\\","/")
  expected=(Path("quarantine")/str(item["instance_id"])/str(item["transfer_id"])/filename).as_posix()
  if relative!=expected:raise ValueError("A confirmação do upload pelo Agent não corresponde ao arquivo.")
  path,_=self.transfers.controller_artifact(str(item["transfer_id"]))
  metadata=body.get("metadata") if isinstance(body.get("metadata"),Mapping) else {}
  preview,_,bundle,children=build_serverpack_bundle(self.root,context,item,relative,cid,metadata,path)
  self._serverpack_capacity(context,cid,children)
  plan=self._serverpack_revision_plan(context,cid,bundle)
  preview["update_plan"]=plan
  return preview

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
    history_before=self.content.bundle_history(iid,content_id)
    previous_bundle_revision=int(history_before[0]["revision"]) if history_before else None
    diff=self.content.bundle_diff(iid,content_id,bundle)
    parent_meta=dict(parent.get("metadata") or {})
    parent_meta["revision_source"]={"kind":"external-upload","filename":name,"transfer_id":tid}
    parent["metadata"]=parent_meta
    result=self.content.put_bundle(parent,bundle,children,requested_by=str(user.get("username") or "customer"))
    result["manifest_diff"]=diff
    result["previous_bundle_revision"]=previous_bundle_revision if result.get("changed") else None
    result["revision_source"]="external-upload"
    return result
   if lower.endswith(".zip") and self._detect_curseforge_export(item):
    raise ValueError("Pacote CurseForge detectado: a exportação normal exige 3rd Party API Key e respeita as restrições de distribuição dos autores. Use o ZIP oficial de servidor para importação manual validada.")
   if lower.endswith(".zip"):
    if not effective.mods_allowed:raise PermissionError("Mods não são permitidos neste contrato.")
    path,_=self.transfers.controller_artifact(tid)
    preview,parent,bundle,children=build_serverpack_bundle(self.root,context,item,relative,content_id,metadata,path)
    self._serverpack_capacity(context,content_id,children)
    declaration=metadata.get("serverpack") if isinstance(metadata.get("serverpack"),Mapping) else {}
    if "expected_revision" not in declaration:
     raise ValueError("Importação recusada: execute a prévia e confirme a revisão antes de instalar.")
    plan=self._serverpack_revision_plan(context,content_id,bundle,
                                        declaration.get("expected_revision"))
    if plan["operation"]=="update":
     if declaration.get("backup_confirmed") is not True:
      raise ValueError("Confirme um backup concluído antes de atualizar o Server Pack.")
     parent_meta=dict(parent.get("metadata") or {})
     parent_meta["serverpack_update_policy"]="preserve-existing-config"
     parent_meta["serverpack_previous_revision"]=plan["previous_revision"]
     parent["metadata"]=parent_meta
    preview["update_plan"]=plan
    history_before=self.content.bundle_history(iid,content_id)
    previous_bundle_revision=int(history_before[0]["revision"]) if history_before else None
    diff=self.content.bundle_diff(iid,content_id,bundle)
    result=self.content.put_bundle(parent,bundle,children,requested_by=str(user.get("username") or "customer"))
    result["serverpack_preview"]=preview
    result["manifest_diff"]=diff
    result["previous_bundle_revision"]=previous_bundle_revision if result.get("changed") else None
    result["revision_source"]="official-serverpack-upload"
    return result
   raise ValueError("Modpack exige .mrpack ou ZIP oficial de servidor validado.")
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
