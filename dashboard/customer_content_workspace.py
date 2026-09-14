#!/usr/bin/env python3
"""Customer-scoped facade for Universal Content desired state."""
from __future__ import annotations
from typing import Mapping
from content_repository import ContentRepository
from customer_instance_workspace_service import CustomerInstanceWorkspaceService
from runtime_workspace_catalog import runtime_definition
from steam_workshop_resolver import resolve_workshop_item
from minecraft_content_resolver import discover_minecraft_content,resolve_minecraft_content
from minecraft_modpack_resolver import resolve_minecraft_modpack

_CUSTOMER_PROVIDERS=frozenset({"steam","steam-workshop","http","http-archive","github","modrinth","curseforge"})
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
  if provider not in _CUSTOMER_PROVIDERS:raise PermissionError("content provider is not customer-managed")
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
  clean_artifact={key:value for key,value in dict(artifact).items() if key not in {"url","download_url","published_file_id","consumer_app_id","package_id","provider"}};clean_artifact.update({"provider":"steam-workshop","package_id":resolved["package_id"]})
  metadata=dict(payload.get("metadata") or {});metadata["steam_workshop"]=dict(resolved["metadata"])
  provenance=dict(payload.get("provenance") or {});provenance["steam_workshop"]={"published_file_id":resolved["published_file_id"],"consumer_app_id":resolved["consumer_app_id"]}
  payload["provider"]="steam-workshop";payload["artifact"]=clean_artifact;payload["metadata"]=metadata;payload["provenance"]=provenance
  return payload
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
 def _existing(self,instance_id,content_id):
  item=self.content.get(instance_id,content_id)
  if item is None:raise KeyError("content assignment not found")
  return item
 def _desired(self,item):
  return {key:item.get(key) for key in _INSTALL_FIELDS if key in item and key not in {"source"}}
 def list(self,user,instance_id):
  self._context_policy(user,instance_id,"content.read");return self.content.customer_view(instance_id,limit=2000)
 def search(self,user,instance_id,provider,content_type,query,limit=20):
  context,capabilities,policy=self._context_policy_details(user,instance_id,"content.read");provider=str(provider or "").strip().lower();ctype=str(content_type or "").strip().lower();text=str(query or "").strip()
  if not text:raise ValueError("search query is required")
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
  context,policy=self._context_policy(user,instance_id,"content.install");payload=self._customer_payload(body);payload["instance_id"]=instance_id;payload["desired_state"]="installed";self._enforce_policy(payload,policy);self._enforce_structured_provider(context,payload)
  modpack=self._resolve_minecraft_modpack(context,payload)
  if modpack is not None:
   parent,bundle,children=modpack;return self.content.put_bundle(parent,bundle,children,requested_by=str(user.get("username") or "customer"))
  self._resolve_workshop(context,payload);self._resolve_minecraft_provider(context,payload);return self.content.put(payload,requested_by=str(user.get("username") or "customer"))
 def mutate(self,user,instance_id,content_id,action,body=None):
  action=str(action or "").strip().lower();required="content.remove" if action=="remove" else "content.install";context,policy=self._context_policy(user,instance_id,required);current=self._existing(instance_id,content_id)
  if str(current.get("content_type") or "").lower()=="modpack":
   self._enforce_policy(current,policy)
   if action=="remove":return self.content.set_bundle_state(instance_id,content_id,desired_state="absent",activation_state="disabled",requested_by=str(user.get("username") or "customer"))
   if action=="disable":return self.content.set_bundle_state(instance_id,content_id,desired_state="installed",activation_state="disabled",requested_by=str(user.get("username") or "customer"))
   if action=="enable":return self.content.set_bundle_state(instance_id,content_id,desired_state="installed",activation_state="enabled",requested_by=str(user.get("username") or "customer"))
   raise ValueError("modpack update/reorder requires Universal Content update orchestration")
  payload=self._desired(current);payload["instance_id"]=instance_id;resolve_update=False
  if action=="remove":payload["desired_state"]="absent";payload["activation_state"]="disabled"
  elif action=="enable":payload["desired_state"]="installed";payload["activation_state"]="enabled"
  elif action=="disable":payload["desired_state"]="installed";payload["activation_state"]="disabled"
  elif action=="reorder":payload["activation_order"]=(body or {}).get("activation_order")
  elif action=="update":
   changes=self._customer_payload(body or {},update=True);payload.update(changes);payload["desired_state"]="installed";resolve_update=bool({"provider","artifact","version"}.intersection(changes))
  else:raise ValueError("invalid content action")
  self._enforce_policy(payload,policy)
  if resolve_update:self._enforce_structured_provider(context,payload);self._resolve_workshop(context,payload);self._resolve_minecraft_provider(context,payload)
  return self.content.put(payload,requested_by=str(user.get("username") or "customer"))

__all__=["CustomerContentWorkspaceService"]
