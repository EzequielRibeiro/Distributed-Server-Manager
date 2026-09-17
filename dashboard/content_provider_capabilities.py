#!/usr/bin/env python3
"""Canonical provider-level capabilities for Universal Content Management."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

_CAPABILITY_KEYS=("customer_managed","discover","install","update","external_upload")
_UPDATE_MODES=frozenset({"server-authoritative","unsupported"})
_DEFAULT={key:False for key in _CAPABILITY_KEYS}

class ContentProviderCapabilityError(RuntimeError):
 pass

def _manifest_path(root=None):
 if root is not None:
  candidate=Path(root)/"catalog"/"v2"/"content-provider-capabilities.json"
  if candidate.is_file():return candidate
 return Path(__file__).resolve().parents[1]/"catalog"/"v2"/"content-provider-capabilities.json"

def load_provider_capabilities(root=None):
 path=_manifest_path(root)
 try:data=json.loads(path.read_text(encoding="utf-8"))
 except (OSError,json.JSONDecodeError) as exc:raise ContentProviderCapabilityError("content provider capability matrix is unavailable") from exc
 if not isinstance(data,Mapping) or data.get("kind")!="ContentProviderCapabilityMatrix" or int(data.get("schema_version") or 0)!=1:raise ContentProviderCapabilityError("invalid content provider capability matrix")
 actions=data.get("actions");providers=data.get("providers");aliases=data.get("aliases") or {}
 if actions!=list(_CAPABILITY_KEYS) or not isinstance(providers,Mapping) or not isinstance(aliases,Mapping):raise ContentProviderCapabilityError("invalid content provider capability matrix contract")
 normalized={}
 for provider,value in providers.items():
  key=str(provider or "").strip().lower()
  if not key or key in normalized or not isinstance(value,Mapping):raise ContentProviderCapabilityError("invalid content provider capability entry")
  entry={}
  for capability in _CAPABILITY_KEYS:
   flag=value.get(capability)
   if type(flag) is not bool:raise ContentProviderCapabilityError(f"provider {key} must explicitly declare {capability}")
   entry[capability]=flag
  mode=str(value.get("update_mode") or "").strip().lower()
  if mode not in _UPDATE_MODES:raise ContentProviderCapabilityError(f"provider {key} has invalid update_mode")
  if entry["update"]!=(mode=="server-authoritative"):raise ContentProviderCapabilityError(f"provider {key} update capability does not match update_mode")
  normalized[key]={**entry,"update_mode":mode}
 clean_aliases={}
 for alias,target in aliases.items():
  alias_key=str(alias or "").strip().lower();target_key=str(target or "").strip().lower()
  if not alias_key or target_key not in normalized or alias_key in normalized:raise ContentProviderCapabilityError("invalid content provider alias")
  clean_aliases[alias_key]=target_key
 return {"schema_version":1,"kind":"ContentProviderCapabilityMatrix","actions":list(_CAPABILITY_KEYS),"aliases":clean_aliases,"providers":normalized}

def normalize_provider(provider,root=None):
 key=str(provider or "").strip().lower()
 if not key:return ""
 try:matrix=load_provider_capabilities(root)
 except ContentProviderCapabilityError:return key
 return matrix["aliases"].get(key,key)

def provider_capabilities(provider,root=None):
 try:
  matrix=load_provider_capabilities(root);key=matrix["aliases"].get(str(provider or "").strip().lower(),str(provider or "").strip().lower());entry=matrix["providers"].get(key)
 except ContentProviderCapabilityError:return dict(_DEFAULT)
 if not isinstance(entry,Mapping):return dict(_DEFAULT)
 return {capability:bool(entry.get(capability,False)) for capability in _CAPABILITY_KEYS}|{"update_mode":str(entry.get("update_mode") or "unsupported")}

def provider_supports(provider,action,root=None):
 action=str(action or "").strip().lower()
 if action not in _CAPABILITY_KEYS:return False
 return bool(provider_capabilities(provider,root).get(action,False))

def customer_managed_providers(root=None,*,include_aliases=True):
 matrix=load_provider_capabilities(root);values={key for key,entry in matrix["providers"].items() if entry["customer_managed"]}
 if include_aliases:
  values.update(alias for alias,target in matrix["aliases"].items() if target in values)
 return frozenset(values)

def public_provider_capabilities(root=None):
 matrix=load_provider_capabilities(root)
 return {"schema_version":matrix["schema_version"],"aliases":dict(matrix["aliases"]),"providers":{key:dict(value) for key,value in matrix["providers"].items()}}

__all__=["ContentProviderCapabilityError","customer_managed_providers","load_provider_capabilities","normalize_provider","provider_capabilities","provider_supports","public_provider_capabilities"]
