#!/usr/bin/env python3
"""Customer-scoped facade for Universal Content desired state."""
from __future__ import annotations
import json
from typing import Mapping
from content_repository import ContentRepository
from content_provider_capabilities import provider_capabilities,provider_supports
from customer_instance_workspace_service import CustomerInstanceWorkspaceService
from runtime_workspace_catalog import runtime_content_activation_capabilities,runtime_definition
from steam_workshop_resolver import resolve_workshop_item
from minecraft_content_resolver import discover_minecraft_content,resolve_minecraft_content
from minecraft_modpack_resolver import resolve_minecraft_modpack

_SERVER_OWNED=frozenset({"agent_id","game_id","security_state","assignment_id","revision","checksum","requested_by","created_at","updated_at"})
_INSTALL_FIELDS=frozenset({"content_id","content_type","desired_state","activation_state","activation_order","version","provider","target","artifact","provenance","source","metadata","dependencies","conflicts"})
_UPDATE_FIELDS=frozenset({"activation_state","activation_order","version","provider","target","artifact","provenance","source","metadata","dependencies","conflicts"})
_ENVELOPE_FIELDS=frozenset({"instance_id","content_id","action"})

class CustomerContentWorkspaceService:
 def __init__(self,backend,root):
  self.workspace=CustomerInstanceWorkspaceService(backend,root);self.content=ContentRepository(backend);self.workshop_resolver=resolve_workshop_item;self.minecraft_resolver=resolve_minecraft_content;self.minecraft_discovery=discover_minecraft_content;self.modpack_resolver=resolve_minecraft_modpack
 def _context_policy_details(self,user,instance_id,permission):
  context=self.workspace.require(user,instance_id,permission);policy=self.workspace.repo.workspace_policy(instance_id);capabilities,content_policy=self.workspace._contract_policy(context,policy);return context,capabilities,content_policy
 def _context_policy(self,user,instance_id,permission):
  context,_,content_policy=self._context_policy_details(user,instance_id,permission);return context,content_policy
 def _reject_server_owned(self,body):
  bad=sorted(_SERVER_OWNED.intersection((body or {}).keys()))
  if bad:raise PermissionError("server-owned content fields cannot be supplied: "+", ".join(bad))
 def _customer_payload(self,body,*,update=False):
  if not isinstance(body,Mapping):raise ValueError("content payload must be an object")
  self._reject_server_owned(body);allowed=_UPDATE_FIELDS if update else _INSTALL_FIELDS;unknown=sorted(set(body)-allowed-_ENVELOPE_FIELDS)
  if unknown:raise ValueError("unsupported content fields: "+", ".join(unknown))
  value={key:body[key] for key in allowed if key in body}
  if "source" in value:
   if "provenance" in value:raise ValueError("use provenance or source, not both")
   value["provenance"]=value.pop("source")
  return value
 def _enforce_policy(self,item,policy):
  provider=str(item.get("provider") or (item.get("artifact") or {}).get("provider") or "").strip().lower();ctype=str(item.get("content_type") or "other").strip().lower()
  if not provider_supports(provider,"customer_managed",self.workspace.root):raise PermissionError("content provider is not customer-managed")
  if provider in {"steam","steam-workshop"} or ctype=="workshop":
   if not policy.workshop_allowed:raise PermissionError("workshop content is not allowed by this contract")
  elif ctype=="plugin":
   if not policy.plugins_allowed:raise PermissionError("plugins are not allowed by this contract")
  elif ctype=="modpack":
   if not policy.modpacks_allowed:raise PermissionError("modpacks are not allowed by this contract")
  elif ctype=="datapack":
   if not policy.datapacks_allowed:raise PermissionError("datapacks are not allowed by this contract")
  elif ctype in {"mod","map"}:
   if not policy.mods_allowed:raise PermissionError("mods are not allowed by this contract")
  elif not policy.modifications_allowed:raise PermissionError("managed content is not allowed by this contract")
 def _enforce_structured_provider(self,context,payload):
  artifact=payload.get("artifact") if isinstance(payload.get("artifact"),Mapping) else {};provider=str(payload.get("provider") or artifact.get("provider") or "").strip().lower();ctype=str(payload.get("content_type") or "other").strip().lower()
  if provider not in {"modrinth","curseforge"}:return
  game_id=str(context.get("game_id") or "").strip().lower();runtime_id=str(context.get("runtime_id") or "").strip()
  if game_id!="minecraft" or not runtime_id:raise PermissionError("structured Minecraft provider is unavailable for this runtime")
  definition=runtime_definition(self.workspace.root,game_id,runtime_id);content=definition.get("content") if isinstance(definition,Mapping) else {}
  if ctype=="modpack":declaration=((content.get("bundles") or {}).get("modpack") or {}) if isinstance(content,Mapping) else {}
  else:declaration=(((content.get("managed") or {}).get("types") or {}).get(ctype) or {}) if isinstance(content,Mapping) else {}
  providers={str(value).strip().lower() for value in (declaration.get("providers") or []) if str(value).strip()} if isinstance(declaration,Mapping) else set()
  if provider not in providers:raise PermissionError("content provider is not declared for this runtime/content type")
 def _resolve_workshop(self,context,payload):
  artifact=payload.get("artifact") if isinstance(payload.get("artifact"),Mapping) else {};provider=str(payload.get("provider") or artifact.get("provider") or "").strip().lower();ctype=str(payload.get("content_type") or "other").strip().lower()
  if provider not in {"steam","steam-workshop"} and ctype!="workshop":return payload
  runtime_id=str(context.get("runtime_id") or "").strip();game_id=str(context.get("game_id") or "").strip().lower()
  if not runtime_id or not game_id:raise ValueError("instance runtime identity is unavailable")
  definition=runtime_definition(self.workspace.root,game_id,runtime_id);workshop=((definition.get("content") or {}).get("steam_workshop") or {}) if isinstance(definition,Mapping) else {};app_id=str(workshop.get("app_id") or "").strip()
  if not app_id:raise PermissionError("Steam Workshop is not configured for this runtime")
  reference=str(artifact.get("package_id") or artifact.get("url") or artifact.get("published_file_id") or "").strip()
  if not reference:raise ValueError("Steam Workshop PublishedFileId or URL is required")
  resolved=getattr(self,"workshop_resolver",resolve_workshop_item)(reference,expected_app_id=app_id)
  clean_artifact={key:value for key,value in dict(artifact).items() if key not in {"url","download_url","published_file_id","consumer_app_id","package_id","provider","revision","auth"}}
  runtime_artifact=definition.get("artifact") if isinstance(definition,Mapping) and isinstance(definition.get("artifact"),Mapping) else {}
  workshop_auth=str(workshop.get("auth") or runtime_artifact.get("auth") or "anonymous").strip().lower()
  if workshop_auth not in {"anonymous","required"}:raise ValueError("Steam Workshop auth policy is invalid")
  revision=str((resolved.get("metadata") or {}).get("time_updated") or "").strip()
  clean_artifact.update({"provider":"steam-workshop","package_id":resolved["package_id"],"auth":workshop_auth})
  if revision.isdigit():
   clean_artifact["revision"]=revision
   payload["version"]=revision
  metadata=dict(payload.get("metadata") or {});metadata["steam_workshop"]=dict(resolved["metadata"])
  provenance=dict(payload.get("provenance") or {});provenance["steam_workshop"]={"published_file_id":resolved["published_file_id"],"consumer_app_id":resolved["consumer_app_id"]}
  payload["provider"]="steam-workshop";payload["artifact"]=clean_artifact;payload["metadata"]=metadata;payload["provenance"]=provenance
  return payload
 def _resolve_workshop_dependencies(self,context,payload):
  metadata=payload.get("metadata") if isinstance(payload.get("metadata"),Mapping) else {};marker=metadata.get("steam_workshop") if isinstance(metadata.get("steam_workshop"),Mapping) else {};root_id=str(marker.get("published_file_id") or "").strip()
  if not root_id:return []
  runtime_id=str(context.get("runtime_id") or "").strip();game_id=str(context.get("game_id") or "").strip().lower();definition=runtime_definition(self.workspace.root,game_id,runtime_id);workshop=((definition.get("content") or {}).get("steam_workshop") or {}) if isinstance(definition,Mapping) else {};graph=workshop.get("required_items") if isinstance(workshop.get("required_items"),Mapping) else {}
  if not graph:return []
  resolved_items={};visiting=set()
  def visit(published_id):
   published_id=str(published_id or "").strip()
   if published_id in visiting:raise ValueError("Steam Workshop dependency cycle detected")
   if published_id in resolved_items:return
   visiting.add(published_id);direct=[str(value).strip() for value in (graph.get(published_id) or []) if str(value).strip()]
   for dep in direct:visit(dep)
   if published_id!=root_id:
    item={"instance_id":str(payload.get("instance_id") or context.get("id") or ""),"content_id":f"steam-workshop:{published_id}","content_type":"workshop","provider":"steam-workshop","desired_state":"installed","activation_state":"enabled","activation_order":int(payload.get("activation_order") or 0),"artifact":{"provider":"steam-workshop","package_id":published_id},"dependencies":[f"steam-workshop:{dep}" for dep in direct]}
    self._resolve_workshop(context,item);self._prepare_activation_defaults(context,item);dep_meta=dict(item.get("metadata") or {});dep_meta["dependency"]={"auto_managed":True,"required_by":root_id};item["metadata"]=dep_meta;resolved_items[published_id]=item
   visiting.remove(published_id)
  direct_root=[str(value).strip() for value in (graph.get(root_id) or []) if str(value).strip()]
  for dep in direct_root:visit(dep)
  payload["dependencies"]=[f"steam-workshop:{dep}" for dep in direct_root]
  return [resolved_items[key] for key in resolved_items]
 def _resolve_minecraft_provider(self,context,payload):
  artifact=payload.get("artifact") if isinstance(payload.get("artifact"),Mapping) else {};provider=str(payload.get("provider") or artifact.get("provider") or "").strip().lower()
  if provider not in {"modrinth","curseforge"}:return payload
  if str(context.get("game_id") or "").strip().lower()!="minecraft":raise PermissionError("Minecraft content provider cannot be used by this game")
  runtime_id=str(context.get("runtime_id") or "").strip();game_version=str(context.get("game_version") or "").strip();ctype=str(payload.get("content_type") or "other").strip().lower()
  if ctype=="modpack":return payload
  if not runtime_id or not game_version:raise ValueError("Minecraft runtime/version identity is unavailable")
  definition=runtime_definition(self.workspace.root,"minecraft",runtime_id)
  if not definition:raise ValueError("Minecraft RuntimeDefinition is unavailable")
  project=str(artifact.get("package_id") or artifact.get("project_id") or artifact.get("slug") or "").strip()
  if not project:raise ValueError(f"{provider} project reference is required")
  resolved=getattr(self,"minecraft_resolver",resolve_minecraft_content)(provider,project,game_version,definition,ctype)
  metadata=dict(payload.get("metadata") or {});metadata["minecraft_provider"]=dict(resolved.get("metadata") or {})
  payload["provider"]=provider;payload["version"]=str(resolved["version"]);payload["artifact"]=dict(resolved["artifact"]);payload["provenance"]={"minecraft_provider":dict(resolved.get("provenance") or {})};payload["metadata"]=metadata
  return payload
 def _resolve_minecraft_modpack(self,context,payload):
  artifact=payload.get("artifact") if isinstance(payload.get("artifact"),Mapping) else {};provider=str(payload.get("provider") or artifact.get("provider") or "").strip().lower();ctype=str(payload.get("content_type") or "").strip().lower()
  if ctype!="modpack" or provider not in {"modrinth","curseforge"}:return None
  if str(context.get("game_id") or "").strip().lower()!="minecraft":raise PermissionError("Minecraft modpack provider cannot be used by this game")
  runtime_id=str(context.get("runtime_id") or "").strip();game_version=str(context.get("game_version") or "").strip();content_id=str(payload.get("content_id") or "").strip()
  if not runtime_id or not game_version or not content_id:raise ValueError("Minecraft runtime/version/content identity is unavailable")
  definition=runtime_definition(self.workspace.root,"minecraft",runtime_id)
  if not definition:raise ValueError("Minecraft RuntimeDefinition is unavailable")
  project=str(artifact.get("package_id") or artifact.get("project_id") or artifact.get("slug") or "").strip()
  if not project:raise ValueError(f"{provider} modpack project reference is required")
  resolved=getattr(self,"modpack_resolver",resolve_minecraft_modpack)(provider,project,content_id,game_version,definition)
  parent=dict(payload);parent["provider"]=provider;parent["version"]=str(resolved["parent"]["version"]);parent["artifact"]=dict(resolved["parent"]["artifact"]);parent["provenance"]={"minecraft_modpack":dict(resolved["parent"].get("provenance") or {})};metadata=dict(parent.get("metadata") or {});metadata["minecraft_modpack"]={"provider":provider,"provider_project_id":resolved["bundle"]["provider_project_id"],"provider_version_id":resolved["bundle"]["provider_version_id"],"minecraft_version":resolved["bundle"]["minecraft_version"],"loader_id":resolved["bundle"]["loader_id"],"loader_version":resolved["bundle"]["loader_version"]};parent["metadata"]=metadata
  children=[]
  for child in resolved["children"]:
   item=dict(child);item["instance_id"]=str(context.get("id") or payload.get("instance_id") or "");children.append(item)
  return parent,dict(resolved["bundle"]),children
 def _mark_update_checkpoint(self,current,payload,*,bundle_revision=None):
  provenance=dict(payload.get("provenance") or {});checkpoint={"previous_revision":int(current.get("revision") or 0),"previous_checksum":str(current.get("checksum") or ""),"previous_version":str(current.get("version") or ""),"activation_state":str(current.get("activation_state") or "enabled"),"activation_order":int(current.get("activation_order") or 0)}
  if bundle_revision is not None:checkpoint["previous_bundle_revision"]=int(bundle_revision)
  provenance["update_checkpoint"]=checkpoint;payload["provenance"]=provenance;return payload
 def _validate_update_request(self,body):
  keys=set((body or {}).keys())-_ENVELOPE_FIELDS
  owned=keys&_SERVER_OWNED
  if owned:raise PermissionError("server-owned content fields cannot be supplied: "+", ".join(sorted(owned)))
  unknown=keys-_UPDATE_FIELDS
  if unknown:raise ValueError("unsupported content fields: "+", ".join(sorted(unknown)))
  if keys:raise PermissionError("content update source/version fields are server-owned")
 def _provider_project_reference(self,item):
  provider=str(item.get("provider") or "").strip().lower();metadata=item.get("metadata") if isinstance(item.get("metadata"),Mapping) else {};provenance=item.get("provenance") if isinstance(item.get("provenance"),Mapping) else {};artifact=item.get("artifact") if isinstance(item.get("artifact"),Mapping) else {}
  if str(item.get("content_type") or "").lower()=="modpack":
   marker=metadata.get("minecraft_modpack") if isinstance(metadata.get("minecraft_modpack"),Mapping) else {};value=str(marker.get("provider_project_id") or "").strip()
   if not value:
    marker=provenance.get("minecraft_modpack") if isinstance(provenance.get("minecraft_modpack"),Mapping) else {};value=str(marker.get("project_id") or "").strip()
  else:
   marker=provenance.get("minecraft_provider") if isinstance(provenance.get("minecraft_provider"),Mapping) else {};value=str(marker.get("project_id") or "").strip()
  if value:return value
  package=str(artifact.get("package_id") or "").strip()
  if provider in {"modrinth","curseforge"} and ":" in package:return package.split(":",1)[0]
  return package
 def _existing(self,instance_id,content_id):
  item=self.content.get(instance_id,content_id)
  if item is None:raise KeyError("content assignment not found")
  return item
 def _desired(self,item):
  return {key:item.get(key) for key in _INSTALL_FIELDS if key in item and key not in {"source"}}
 def _activation_configuration(self,context,item):
  game_id=str(context.get("game_id") or item.get("game_id") or "").strip().lower()
  runtime_id=str(context.get("runtime_id") or "").strip().lower()
  ctype=str(item.get("content_type") or "").strip().lower()
  if not game_id or not runtime_id or not ctype:return None
  capabilities=runtime_content_activation_capabilities(self.workspace.root,game_id,runtime_id)
  declaration=(capabilities.get("types") or {}).get(ctype) if isinstance(capabilities,Mapping) else None
  if not isinstance(declaration,Mapping):return None
  modes=[dict(value) for value in declaration.get("modes") or [] if isinstance(value,Mapping)]
  valid={str(value.get("value") or "").strip().lower() for value in modes}
  if not valid:return None
  metadata=item.get("metadata") if isinstance(item.get("metadata"),Mapping) else {}
  activation=metadata.get("activation") if isinstance(metadata.get("activation"),Mapping) else {}
  current_adapter=str(activation.get("adapter") or "").strip().lower()
  adapter=str(capabilities.get("adapter") or "").strip().lower()
  mode=str(activation.get("mode") or declaration.get("default_mode") or "").strip().lower()
  if current_adapter and current_adapter!=adapter:mode=str(declaration.get("default_mode") or "").strip().lower()
  if mode not in valid:mode=str(declaration.get("default_mode") or "").strip().lower()
  identifier=str(activation.get("identifier") or "").strip()
  return {
   "adapter":adapter,
   "mode":mode,
   "modes":modes,
   "identifier":identifier,
   "identifier_required":bool(declaration.get("identifier_required",False)),
   "identifier_label":str(declaration.get("identifier_label") or "Identificador"),
  }

 def _safe_activation_identifier(self,value):
  identifier=str(value or "").strip()
  if not identifier or len(identifier)>191 or any(c in identifier for c in ("\x00","\r","\n",";")):
   raise ValueError("invalid runtime content activation identifier")
  return identifier

 def _prepare_activation_defaults(self,context,payload):
  config=self._activation_configuration(context,payload)
  if config is None:return payload
  metadata=dict(payload.get("metadata") or {})
  metadata["activation"]={"adapter":str(config.get("adapter") or ""),"mode":str(config.get("mode") or "")}
  payload["metadata"]=metadata
  if config.get("identifier_required"):payload["activation_state"]="disabled"
  return payload

 def _configure_activation(self,context,current,body):
  if not isinstance(body,Mapping):raise ValueError("content activation payload must be an object")
  allowed={"instance_id","content_id","action","mode","identifier"}
  unknown=sorted(set(body)-allowed)
  if unknown:raise ValueError("unsupported activation fields: "+", ".join(unknown))
  config=self._activation_configuration(context,current)
  if config is None:raise PermissionError("content activation mode is unavailable for this runtime/content type")
  mode=str(body.get("mode") or "").strip().lower()
  valid={str(item.get("value") or "").strip().lower() for item in config.get("modes") or []}
  if mode not in valid:raise ValueError("unsupported runtime content activation mode")
  required=bool(config.get("identifier_required"))
  identifier=str(body.get("identifier") if "identifier" in body else config.get("identifier") or "").strip()
  if required:identifier=self._safe_activation_identifier(identifier)
  elif identifier:identifier=self._safe_activation_identifier(identifier)
  payload=self._desired(current);payload["instance_id"]=str(current.get("instance_id") or context.get("id") or "")
  metadata=dict(payload.get("metadata") or {})
  next_activation={"adapter":str(config.get("adapter") or ""),"mode":mode}
  if identifier:next_activation["identifier"]=identifier
  metadata["activation"]=next_activation
  payload["metadata"]=metadata
  if required:payload["activation_state"]="enabled"
  return payload
 def _customer_security_projection(self,item):
  state=str(item.get("effective_security_state") or item.get("security_state") or "unscanned").strip().lower()
  reconciliation=dict(item.get("reconciliation") or {})
  status=str(reconciliation.get("status") or "").strip().lower()
  if state in {"blocked","suspicious"} or status=="security_blocked":
   message="Conteúdo bloqueado por segurança: o YARA-X identificou um arquivo suspeito. A instalação foi cancelada."
   reconciliation["last_error"]=message
   item["security_notice"]={"state":state if state in {"blocked","suspicious"} else "blocked","message":message}
  elif state=="scan_failed" or status=="security_scan_failed":
   message="Não foi possível concluir a verificação de segurança do conteúdo. A instalação não foi aplicada."
   reconciliation["last_error"]=message
   item["security_notice"]={"state":"scan_failed","message":message}
  item["reconciliation"]=reconciliation
  return item

 def list(self,user,instance_id):
  context,_,_=self._context_policy_details(user,instance_id,"content.read");items=self.content.customer_view(instance_id,limit=2000)
  for item in items:
   provider=str(item.get("provider") or "").strip().lower();ctype=str(item.get("content_type") or "").strip().lower();rollback_revision=None
   if ctype=="modpack":
    history=self.content.bundle_history(instance_id,str(item.get("content_id") or ""));rollback_revision=int(history[1]["revision"]) if len(history)>1 else None
   else:
    previous=self.content.previous_revision(instance_id,str(item.get("content_id") or ""));rollback_revision=int(previous["revision"]) if previous else None
   item["provider_capabilities"]=provider_capabilities(provider,self.workspace.root);item["update"]={"supported":provider_supports(provider,"update",self.workspace.root),"rollback_available":rollback_revision is not None,"rollback_revision":rollback_revision}
   activation_config=self._activation_configuration(context,item)
   if activation_config is not None:item["activation_config"]=activation_config
   self._customer_security_projection(item)
  return items
 def bundle_details(self,user,instance_id,content_id):
  self._context_policy(user,instance_id,"content.read");parent=self._existing(instance_id,content_id)
  if str(parent.get("content_type") or "").strip().lower()!="modpack":raise ValueError("content is not a modpack bundle")
  history=self.content.bundle_history(instance_id,content_id)
  if not history:raise KeyError("content bundle not found")
  def manifest(row):
   try:value=json.loads(row.get("manifest_json") or "{}")
   except (TypeError,json.JSONDecodeError):raise ValueError("stored content bundle manifest is invalid")
   if not isinstance(value,dict) or not isinstance(value.get("members"),list):raise ValueError("stored content bundle manifest is invalid")
   return value
  current_row=history[0];current_manifest=manifest(current_row);members={str(item.get("content_id") or ""):item for item in current_manifest.get("members") or [] if isinstance(item,Mapping) and str(item.get("content_id") or "").strip()}
  assignments={str(item.get("content_id") or ""):item for item in self.content.list(instance_id=instance_id,limit=2000)}
  reasons=[];visible=[]
  for cid in sorted(members):
   declared=members[cid];item=assignments.get(cid)
   if not item:
    reasons.append({"content_id":cid,"reason":"missing_member"});visible.append({"content_id":cid,"state":"missing"});continue
   marker=(item.get("metadata") or {}).get("bundle") if isinstance(item.get("metadata"),Mapping) else None
   owned=isinstance(marker,Mapping) and str(marker.get("parent_content_id") or "")==content_id
   artifact_matches=(item.get("artifact") or {})==(declared.get("artifact") or {})
   active=str(item.get("desired_state") or "installed")!="absent"
   if not owned:reasons.append({"content_id":cid,"reason":"ownership_drift"})
   elif not artifact_matches:reasons.append({"content_id":cid,"reason":"artifact_drift"})
   elif not active:reasons.append({"content_id":cid,"reason":"member_absent"})
   visible.append({"content_id":cid,"content_type":str(item.get("content_type") or "mod"),"provider":str(item.get("provider") or ""),"version":str(item.get("version") or ""),"desired_state":str(item.get("desired_state") or "installed"),"activation_state":str(item.get("activation_state") or "enabled"),"security_state":str(item.get("security_state") or "unscanned"),"state":"managed" if owned and artifact_matches and active else "customized"})
  extras=[]
  for cid,item in assignments.items():
   if cid==content_id or cid in members or str(item.get("desired_state") or "installed")=="absent":continue
   marker=(item.get("metadata") or {}).get("bundle") if isinstance(item.get("metadata"),Mapping) else None
   if isinstance(marker,Mapping) and str(marker.get("parent_content_id") or "")==content_id:
    extras.append(cid);reasons.append({"content_id":cid,"reason":"extra_member"})
  diff={"added":[],"removed":[],"updated":[],"unchanged":[]}
  if len(history)>1:
   previous=manifest(history[1]);old={str(item.get("content_id") or ""):item for item in previous.get("members") or [] if isinstance(item,Mapping) and str(item.get("content_id") or "").strip()}
   diff["added"]=sorted(set(members)-set(old));diff["removed"]=sorted(set(old)-set(members));diff["updated"]=sorted(cid for cid in set(old)&set(members) if (old[cid].get("artifact") or {})!=(members[cid].get("artifact") or {}));diff["unchanged"]=sorted((set(old)&set(members))-set(diff["updated"]))
  return {"content_id":content_id,"content_type":"modpack","provider":str(parent.get("provider") or ""),"version":str(parent.get("version") or ""),"bundle_state":"customized" if reasons else "managed","customization_reasons":reasons,"current_revision":int(current_row.get("revision") or 0),"previous_revision":int(history[1].get("revision") or 0) if len(history)>1 else None,"minecraft_version":str(current_row.get("minecraft_version") or ""),"loader_id":str(current_row.get("loader_id") or ""),"loader_version":str(current_row.get("loader_version") or ""),"manifest_kind":str(current_row.get("manifest_kind") or ""),"members":visible,"extra_members":sorted(extras),"diff_from_previous":diff,"revisions":[{"revision":int(row.get("revision") or 0),"provider_version_id":str(row.get("provider_version_id") or ""),"created_at":row.get("created_at")} for row in history[:20]]}
 def search(self,user,instance_id,provider,content_type,query,limit=20):
  context,capabilities,policy=self._context_policy_details(user,instance_id,"content.read");provider=str(provider or "").strip().lower();ctype=str(content_type or "").strip().lower();text=str(query or "").strip()
  if not text:raise ValueError("search query is required")
  if not provider_supports(provider,"discover",self.workspace.root):raise PermissionError("content provider discovery is unavailable")
  self._enforce_policy({"provider":provider,"content_type":ctype},policy)
  allowed={str(value).strip().lower() for value in ((capabilities.get("providers") or {}).get(ctype) or []) if str(value).strip()}
  if provider not in allowed:raise PermissionError("content provider is not available for this runtime/content type")
  if provider=="steam-workshop":
   runtime_id=str(context.get("runtime_id") or "").strip();definition=runtime_definition(self.workspace.root,str(context.get("game_id") or ""),runtime_id);workshop=((definition.get("content") or {}).get("steam_workshop") or {}) if isinstance(definition,Mapping) else {};app_id=str(workshop.get("app_id") or "").strip()
   if not app_id:raise PermissionError("Steam Workshop is not configured for this runtime")
   resolved=getattr(self,"workshop_resolver",resolve_workshop_item)(text,expected_app_id=app_id);meta=dict(resolved.get("metadata") or {});return [{"provider":"steam-workshop","content_type":"workshop","content_id":f"steam-workshop:{resolved['published_file_id']}","project_ref":resolved["published_file_id"],"project_id":resolved["published_file_id"],"slug":resolved["published_file_id"],"name":str(meta.get("title") or f"Workshop {resolved['published_file_id']}")[:300],"description":"Steam Workshop","author":str(meta.get("creator") or "")[:200],"downloads":0,"icon_url":"","project_type":"workshop"}]
  if str(context.get("game_id") or "").strip().lower()!="minecraft":raise PermissionError("provider discovery is unavailable for this game")
  runtime_id=str(context.get("runtime_id") or "").strip();game_version=str(context.get("game_version") or "").strip();definition=runtime_definition(self.workspace.root,"minecraft",runtime_id)
  if not runtime_id or not game_version or not definition:raise ValueError("Minecraft runtime/version identity is unavailable")
  try:count=max(1,min(int(limit),50))
  except (TypeError,ValueError):count=20
  return getattr(self,"minecraft_discovery",discover_minecraft_content)(provider,text,game_version,definition,ctype,limit=count)
 def install(self,user,instance_id,body):
  context,policy=self._context_policy(user,instance_id,"content.install");payload=self._customer_payload(body);payload["instance_id"]=instance_id;payload["desired_state"]="installed";provider=str(payload.get("provider") or (payload.get("artifact") or {}).get("provider") or "").strip().lower()
  if not provider_supports(provider,"install",self.workspace.root):raise PermissionError("content provider install is unavailable")
  self._enforce_policy(payload,policy);self._enforce_structured_provider(context,payload)
  modpack=self._resolve_minecraft_modpack(context,payload)
  if modpack is not None:
   parent,bundle,children=modpack;return self.content.put_bundle(parent,bundle,children,requested_by=str(user.get("username") or "customer"))
  self._resolve_workshop(context,payload);dependencies=self._resolve_workshop_dependencies(context,payload);self._resolve_minecraft_provider(context,payload);self._prepare_activation_defaults(context,payload);actor=str(user.get("username") or "customer")
  if dependencies:
   result=self.content.put_many([*dependencies,payload],requested_by=actor);result["assignment"]=next(item for item in result["assignments"] if str(item.get("content_id") or "")==str(payload.get("content_id") or ""));result["dependencies"]=[item for item in result["assignments"] if str(item.get("content_id") or "")!=str(payload.get("content_id") or "")];return result
  return self.content.put(payload,requested_by=actor)
 def mutate(self,user,instance_id,content_id,action,body=None):
  action=str(action or "").strip().lower();required="content.remove" if action=="remove" else "content.install";context,policy=self._context_policy(user,instance_id,required);current=self._existing(instance_id,content_id);actor=str(user.get("username") or "customer");ctype=str(current.get("content_type") or "").lower();provider=str(current.get("provider") or "").strip().lower()
  marker=(current.get("metadata") or {}).get("bundle") if isinstance(current.get("metadata"),Mapping) else None
  parent_content_id=str(marker.get("parent_content_id") or "").strip() if isinstance(marker,Mapping) else ""
  if parent_content_id and ctype!="modpack":raise PermissionError("bundle child content must be changed through its parent modpack")
  if ctype=="modpack":
   self._enforce_policy(current,policy)
   if action=="remove":return self.content.set_bundle_state(instance_id,content_id,desired_state="absent",activation_state="disabled",requested_by=actor)
   if action=="disable":return self.content.set_bundle_state(instance_id,content_id,desired_state="installed",activation_state="disabled",requested_by=actor)
   if action=="enable":return self.content.set_bundle_state(instance_id,content_id,desired_state="installed",activation_state="enabled",requested_by=actor)
   if action=="rollback":
    revision=(body or {}).get("revision");return self.content.rollback_bundle(instance_id,content_id,revision,requested_by=actor,reason="customer")
   if action=="update":
    self._validate_update_request(body)
    if not provider_supports(provider,"update",self.workspace.root):raise ValueError("automatic modpack update is unavailable for this provider")
    if provider not in {"modrinth","curseforge"}:raise ValueError("automatic modpack update is unavailable for this provider")
    project=self._provider_project_reference(current)
    if not project:raise ValueError("modpack provider project identity is unavailable")
    payload=self._desired(current);payload["instance_id"]=instance_id;payload["artifact"]={"provider":provider,"package_id":project};payload["desired_state"]="installed";self._enforce_structured_provider(context,payload);resolved=self._resolve_minecraft_modpack(context,payload)
    if resolved is None:raise ValueError("modpack resolver is unavailable")
    parent,bundle,children=resolved;history_before=self.content.bundle_history(instance_id,content_id);current_bundle_revision=int(history_before[0]["revision"]) if history_before else None;self._mark_update_checkpoint(current,parent,bundle_revision=current_bundle_revision);diff=self.content.bundle_diff(instance_id,content_id,bundle);result=self.content.put_bundle(parent,bundle,children,requested_by=actor);result["manifest_diff"]=diff;result["previous_bundle_revision"]=current_bundle_revision if result.get("changed") else None;return result
   raise ValueError("modpack reorder is not supported")
  payload=self._desired(current);payload["instance_id"]=instance_id
  if action=="remove":payload["desired_state"]="absent";payload["activation_state"]="disabled"
  elif action=="enable":payload["desired_state"]="installed";payload["activation_state"]="enabled"
  elif action=="disable":payload["desired_state"]="installed";payload["activation_state"]="disabled"
  elif action=="reorder":payload["activation_order"]=(body or {}).get("activation_order")
  elif action=="configure-activation":payload=self._configure_activation(context,current,body or {})
  elif action=="rollback":
   revision=(body or {}).get("revision");return self.content.rollback(instance_id,content_id,revision,requested_by=actor,reason="customer")
  elif action=="update":
   self._validate_update_request(body)
   if not provider_supports(provider,"update",self.workspace.root):raise ValueError("automatic content update is unavailable for this provider")
   payload["desired_state"]="installed"
   if provider in {"modrinth","curseforge"}:
    project=self._provider_project_reference(current)
    if not project:raise ValueError("content provider project identity is unavailable")
    payload["artifact"]={"provider":provider,"package_id":project};self._enforce_structured_provider(context,payload);self._resolve_minecraft_provider(context,payload)
   elif provider in {"steam","steam-workshop"}:self._resolve_workshop(context,payload)
   else:raise ValueError("automatic content update is unavailable for this provider")
   self._mark_update_checkpoint(current,payload)
  else:raise ValueError("invalid content action")
  self._enforce_policy(payload,policy)
  if action=="update" and provider in {"steam","steam-workshop"}:
   dependencies=self._resolve_workshop_dependencies(context,payload)
   if dependencies:
    result=self.content.put_many([*dependencies,payload],requested_by=actor);result["assignment"]=next(item for item in result["assignments"] if str(item.get("content_id") or "")==content_id);result["dependencies"]=[item for item in result["assignments"] if str(item.get("content_id") or "")!=content_id];return result
  return self.content.put(payload,requested_by=actor)


__all__=["CustomerContentWorkspaceService"]
