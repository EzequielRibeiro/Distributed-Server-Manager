#!/usr/bin/env python3
"""Universal policy model for the customer instance workspace."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Iterable

INSTANCE_PERMISSIONS=frozenset({"instance.view","instance.start","instance.stop","instance.restart","instance.delete","console.read","console.execute","files.read","files.download","files.upload","files.edit","files.delete","files.move","files.extract","backup.read","backup.create","backup.download","backup.restore","backup.delete","startup.read","startup.write","content.read","content.install","content.remove","team.read","team.manage","contract.read","contract.upgrade"})
PERMISSION_PRESETS={
 "none":frozenset(),"custom":frozenset(),
 "viewer":frozenset({"instance.view","console.read","files.read","files.download","backup.read","startup.read","content.read","team.read","contract.read"}),
 "operator":frozenset({"instance.view","instance.start","instance.stop","instance.restart","console.read","files.read","files.download","files.upload","files.edit","backup.read","backup.create","backup.download","startup.read","content.read","content.install","content.remove","team.read","contract.read"}),
 "manager":INSTANCE_PERMISSIONS,
}
FILE_ACTION_PERMISSION={"list":"files.read","read":"files.read","download":"files.download","upload":"files.upload","edit":"files.edit","delete":"files.delete","move":"files.move","rename":"files.move","mkdir":"files.upload","extract":"files.extract"}
CONTENT_FEATURES=frozenset({"mods","plugins","workshop","external_upload","custom_runtime"})

@dataclass(frozen=True)
class EffectiveContentPolicy:
 modifications_allowed:bool;mods_allowed:bool;plugins_allowed:bool;workshop_allowed:bool;external_upload_allowed:bool;custom_runtime_allowed:bool
 def as_dict(self):return {"modifications_allowed":self.modifications_allowed,"mods_allowed":self.mods_allowed,"plugins_allowed":self.plugins_allowed,"workshop_allowed":self.workshop_allowed,"external_upload_allowed":self.external_upload_allowed,"custom_runtime_allowed":self.custom_runtime_allowed}

def permissions_for_profile(profile):
 name=str(profile or "viewer").strip().lower()
 return set(PERMISSION_PRESETS.get(name,PERMISSION_PRESETS["viewer"]))
def effective_permissions(profile,grants=None):
 result=permissions_for_profile(profile)
 for permission,allowed in (grants or {}).items():
  if permission not in INSTANCE_PERMISSIONS:continue
  if allowed:result.add(permission)
  else:result.discard(permission)
 return result
def require_permission(permissions:Iterable[str],permission:str):
 if permission not in INSTANCE_PERMISSIONS:raise ValueError("unknown instance permission")
 if permission not in set(permissions):raise PermissionError(f"{permission} permission required")
def effective_content_policy(contract_entitlements,runtime_capabilities):
 entitlement=contract_entitlements or {};capability=runtime_capabilities or {}
 def enabled(feature,default=False):return bool(entitlement.get(feature,default)) and bool(capability.get(feature,False))
 mods=enabled("mods");plugins=enabled("plugins");workshop=enabled("workshop");external=enabled("external_upload",True);custom=enabled("custom_runtime")
 return EffectiveContentPolicy(bool(mods or plugins or workshop),mods,plugins,workshop,external,custom)
def content_ui_sections(policy):return [name for name,ok in (("mods",policy.mods_allowed),("plugins",policy.plugins_allowed),("workshop",policy.workshop_allowed)) if ok]
def validate_startup_values(values,declaration):
 supplied=values if isinstance(values,dict) else {};declared=declaration if isinstance(declaration,dict) else {};normalized={}
 for key,value in supplied.items():
  spec=declared.get(key)
  if not isinstance(spec,dict) or not bool(spec.get("customer_editable")):raise PermissionError(f"startup parameter is not customer editable: {key}")
  kind=str(spec.get("type") or "string").lower()
  if kind=="select":
   allowed=list(spec.get("allowed") or [])
   if value not in allowed:raise ValueError(f"invalid value for startup parameter: {key}")
  elif kind=="integer":
   try:value=int(value)
   except (TypeError,ValueError) as exc:raise ValueError(f"startup parameter must be an integer: {key}") from exc
   if spec.get("min") is not None and value<int(spec["min"]):raise ValueError(f"startup parameter below minimum: {key}")
   if spec.get("max") is not None and value>int(spec["max"]):raise ValueError(f"startup parameter above maximum: {key}")
  elif kind=="boolean":value=bool(value)
  elif kind=="string":
   value=str(value)
   if len(value)>int(spec.get("max_length") or 256):raise ValueError(f"startup parameter too long: {key}")
  else:raise ValueError(f"unsupported startup parameter type: {kind}")
  normalized[str(key)]=value
 return normalized
def normalized_instance_relative_path(value):
 path=PurePosixPath(str(value or "").replace("\\","/").strip() or ".")
 if path.is_absolute() or ".." in path.parts:raise ValueError("path must stay inside the instance")
 return path.as_posix()
def enforce_content_upload(relative_path,*,policy,runtime_rules=None):
 path=normalized_instance_relative_path(relative_path).lower();rules=runtime_rules if isinstance(runtime_rules,dict) else {}
 protected=[str(x).strip("/").lower() for x in rules.get("protected_paths",[]) if str(x).strip()]
 if any(path==x or path.startswith(x+"/") for x in protected):raise PermissionError("managed runtime path cannot be modified by customer")
 for rule,allowed,error in (("mod_paths",policy.mods_allowed,"mods are not allowed by this contract"),("plugin_paths",policy.plugins_allowed,"plugins are not allowed by this contract"),("workshop_paths",policy.workshop_allowed,"workshop content is not allowed by this contract")):
  candidates=[str(x).strip("/").lower() for x in rules.get(rule,[]) if str(x).strip()]
  if candidates and any(path==x or path.startswith(x+"/") for x in candidates) and not allowed:raise PermissionError(error)
 if PurePosixPath(path).suffix.lower() in {str(x).lower() for x in rules.get("runtime_extensions",[])} and not policy.custom_runtime_allowed:raise PermissionError("custom runtime artifacts are not allowed by this contract")
 if not policy.external_upload_allowed:raise PermissionError("external file upload is not allowed by this contract")

__all__=["CONTENT_FEATURES","EffectiveContentPolicy","FILE_ACTION_PERMISSION","INSTANCE_PERMISSIONS","PERMISSION_PRESETS","content_ui_sections","effective_content_policy","effective_permissions","enforce_content_upload","normalized_instance_relative_path","permissions_for_profile","require_permission","validate_startup_values"]
