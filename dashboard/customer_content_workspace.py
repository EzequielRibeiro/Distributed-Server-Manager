#!/usr/bin/env python3
"""Customer-scoped facade for Universal Content desired state."""
from __future__ import annotations
from typing import Mapping
from content_repository import ContentRepository
from customer_instance_workspace_service import CustomerInstanceWorkspaceService

_CUSTOMER_PROVIDERS=frozenset({"steam","steam-workshop","http","http-archive","github","modrinth"})
_SERVER_OWNED=frozenset({"agent_id","game_id","security_state","assignment_id","revision","checksum","requested_by","created_at","updated_at"})
_INSTALL_FIELDS=frozenset({"content_id","content_type","desired_state","activation_state","activation_order","version","provider","target","artifact","provenance","source","metadata","dependencies","conflicts"})
_UPDATE_FIELDS=frozenset({"activation_state","activation_order","version","provider","target","artifact","provenance","source","metadata","dependencies","conflicts"})
_ENVELOPE_FIELDS=frozenset({"instance_id","content_id","action"})

class CustomerContentWorkspaceService:
 def __init__(self,backend,root):
  self.workspace=CustomerInstanceWorkspaceService(backend,root);self.content=ContentRepository(backend)
 def _context_policy(self,user,instance_id,permission):
  context=self.workspace.require(user,instance_id,permission);policy=self.workspace.repo.workspace_policy(instance_id);_,content_policy=self.workspace._contract_policy(context,policy);return context,content_policy
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
  elif ctype in {"mod","modpack","map"}:
   if not policy.mods_allowed:raise PermissionError("mods are not allowed by this contract")
  elif not policy.modifications_allowed:raise PermissionError("managed content is not allowed by this contract")
 def _existing(self,instance_id,content_id):
  item=self.content.get(instance_id,content_id)
  if item is None:raise KeyError("content assignment not found")
  return item
 def _desired(self,item):
  return {key:item.get(key) for key in _INSTALL_FIELDS if key in item and key not in {"source"}}
 def list(self,user,instance_id):
  self._context_policy(user,instance_id,"content.read");return self.content.list(instance_id=instance_id,limit=2000)
 def install(self,user,instance_id,body):
  _,policy=self._context_policy(user,instance_id,"content.install");payload=self._customer_payload(body);payload["instance_id"]=instance_id;payload["desired_state"]="installed";self._enforce_policy(payload,policy);return self.content.put(payload,requested_by=str(user.get("username") or "customer"))
 def mutate(self,user,instance_id,content_id,action,body=None):
  action=str(action or "").strip().lower();required="content.remove" if action=="remove" else "content.install";_,policy=self._context_policy(user,instance_id,required);current=self._existing(instance_id,content_id);payload=self._desired(current);payload["instance_id"]=instance_id
  if action=="remove":payload["desired_state"]="absent";payload["activation_state"]="disabled"
  elif action=="enable":payload["desired_state"]="installed";payload["activation_state"]="enabled"
  elif action=="disable":payload["desired_state"]="installed";payload["activation_state"]="disabled"
  elif action=="reorder":payload["activation_order"]=(body or {}).get("activation_order")
  elif action=="update":
   changes=self._customer_payload(body or {},update=True);payload.update(changes);payload["desired_state"]="installed"
  else:raise ValueError("invalid content action")
  self._enforce_policy(payload,policy);return self.content.put(payload,requested_by=str(user.get("username") or "customer"))

__all__=["CustomerContentWorkspaceService"]
