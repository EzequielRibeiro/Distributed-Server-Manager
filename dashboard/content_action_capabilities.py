#!/usr/bin/env python3
"""Server-authoritative effective action projection for managed content items."""
from __future__ import annotations
from typing import Any,Mapping
from content_provider_capabilities import normalize_provider,provider_supports

_ACTIONS=("enable","disable","reorder","update","rollback","remove")

def _type_allowed(content_type:str,policy:Any)->bool:
 ctype=str(content_type or "").strip().lower()
 if ctype=="plugin":return bool(getattr(policy,"plugins_allowed",False))
 if ctype=="modpack":return bool(getattr(policy,"modpacks_allowed",False))
 if ctype=="datapack":return bool(getattr(policy,"datapacks_allowed",False))
 if ctype=="workshop":return bool(getattr(policy,"workshop_allowed",False))
 if ctype in {"mod","map"}:return bool(getattr(policy,"mods_allowed",False))
 return bool(getattr(policy,"modifications_allowed",False))

def _runtime_provider_allowed(provider:str,content_type:str,capabilities:Mapping[str,Any],root)->bool:
 ctype=str(content_type or "").strip().lower();declared=((capabilities.get("providers") or {}).get(ctype) or []) if isinstance(capabilities,Mapping) else []
 canonical=normalize_provider(provider,root)
 return canonical in {normalize_provider(value,root) for value in declared if str(value or "").strip()}

def effective_content_actions(*,item:Mapping[str,Any],permissions:set[str],capabilities:Mapping[str,Any],policy:Any,root)->dict[str,bool]:
 ctype=str(item.get("content_type") or "").strip().lower();provider=str(item.get("provider") or "").strip().lower();desired=str(item.get("desired_state") or "installed").strip().lower();activation=str(item.get("activation_state") or "enabled").strip().lower();installed=desired!="absent";type_allowed=_type_allowed(ctype,policy);can_install="content.install" in permissions;can_remove="content.remove" in permissions
 update=item.get("update") if isinstance(item.get("update"),Mapping) else {};provider_update=provider_supports(provider,"update",root);runtime_provider=_runtime_provider_allowed(provider,ctype,capabilities,root)
 return {
  "enable":bool(can_install and type_allowed and installed and activation!="enabled"),
  "disable":bool(can_install and type_allowed and installed and activation=="enabled"),
  "reorder":bool(can_install and type_allowed and installed and ctype!="modpack"),
  "update":bool(can_install and type_allowed and installed and provider_update and runtime_provider and update.get("supported")),
  "rollback":bool(can_install and type_allowed and installed and update.get("rollback_available")),
  "remove":bool(can_remove and type_allowed and installed),
 }

def project_content_actions(service,user:Mapping[str,Any],instance_id:str,items:list[dict[str,Any]])->list[dict[str,Any]]:
 _context,capabilities,policy=service._context_policy_details(user,instance_id,"content.read")
 permissions=set(service.workspace.permissions(user,instance_id))
 result=[]
 for raw in items:
  item=dict(raw);item["actions"]=effective_content_actions(item=item,permissions=permissions,capabilities=capabilities,policy=policy,root=service.workspace.root);result.append(item)
 return result

__all__=["effective_content_actions","project_content_actions"]
