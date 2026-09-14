#!/usr/bin/env python3
"""Canonical desired-state contract for Capivara Universal Content."""
from __future__ import annotations
import hashlib,json,re
from typing import Any,Mapping
_TOKEN=re.compile(r"^[A-Za-z0-9._:-]{1,191}$")
_TYPES={"mod","plugin","modpack","datapack","map","asset","workshop","other"};_STATES={"installed","absent"};_ACTIVATION_STATES={"enabled","disabled"};_PROVIDERS={"steam","steam-workshop","http","http-archive","github","modrinth","curseforge","local","custom","source-build"}
_FORBIDDEN_ARTIFACT_KEYS={"command","shell","exec","script","password","passwd","token","secret","api_key","apikey","authorization","credential","credentials","steam_password","steam_guard"}
_MAX_STRUCTURED_BYTES=65536
class ContentValidationError(ValueError):pass
def _j(v:Any)->str:return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def _token(v:Any,label:str)->str:
 s=str(v or "").strip()
 if not _TOKEN.fullmatch(s):raise ContentValidationError(f"invalid {label}")
 return s
def _target(v:Any)->str:
 s=str(v or "").strip().replace("\\","/")
 if not s or s.startswith("/") or any(p in {"",".",".."} for p in s.split("/")):raise ContentValidationError("invalid target")
 return s[:500]
def _reject_unsafe_structured(value:Any)->None:
 if isinstance(value,Mapping):
  for key,nested in value.items():
   if str(key).strip().lower() in _FORBIDDEN_ARTIFACT_KEYS:raise ContentValidationError("content metadata may not contain executable commands or credentials")
   _reject_unsafe_structured(nested)
 elif isinstance(value,(list,tuple)):
  for nested in value:_reject_unsafe_structured(nested)
def _structured(raw:Any,label:str)->dict[str,Any]:
 if raw is None:return {}
 if not isinstance(raw,Mapping):raise ContentValidationError(f"{label} must be an object")
 value=dict(raw);_reject_unsafe_structured(value)
 try:encoded=_j(value).encode("utf-8")
 except (TypeError,ValueError) as exc:raise ContentValidationError(f"invalid {label}") from exc
 if len(encoded)>_MAX_STRUCTURED_BYTES:raise ContentValidationError(f"{label} exceeds maximum size")
 return value
def _activation_order(raw:Any)->int:
 if isinstance(raw,bool):raise ContentValidationError("invalid activation_order")
 try:value=int(0 if raw is None or raw=="" else raw)
 except (TypeError,ValueError) as exc:raise ContentValidationError("invalid activation_order") from exc
 if isinstance(raw,float) and raw!=value:raise ContentValidationError("invalid activation_order")
 if value<0 or value>1000000:raise ContentValidationError("invalid activation_order")
 return value
def normalize_assignment(raw:Mapping[str,Any],*,expected_agent_id:str|None=None)->dict[str,Any]:
 if not isinstance(raw,Mapping):raise ContentValidationError("content assignment must be an object")
 agent=_token(raw.get("agent_id") or expected_agent_id,"agent_id")
 if expected_agent_id and agent!=expected_agent_id:raise ContentValidationError("Agent identity mismatch")
 instance=_token(raw.get("instance_id"),"instance_id");content=_token(raw.get("content_id"),"content_id");game=_token(raw.get("game_id"),"game_id").lower();ctype=str(raw.get("content_type") or "other").strip().lower()
 if ctype not in _TYPES:raise ContentValidationError("invalid content_type")
 state=str(raw.get("desired_state") or "installed").strip().lower()
 if state not in _STATES:raise ContentValidationError("invalid desired_state")
 default_activation="enabled" if state=="installed" else "disabled";activation_state=str(raw.get("activation_state") or default_activation).strip().lower()
 if activation_state not in _ACTIVATION_STATES:raise ContentValidationError("invalid activation_state")
 if state=="absent" and activation_state!="disabled":raise ContentValidationError("absent content cannot be enabled")
 activation_order=_activation_order(raw.get("activation_order"))
 artifact=_structured(raw.get("artifact"),"artifact")
 version=str(raw.get("version") or "latest").strip()[:191] or "latest";provider=str(raw.get("provider") or artifact.get("provider") or "").strip().lower()
 if provider not in _PROVIDERS:raise ContentValidationError("invalid provider")
 artifact["provider"]=provider
 provenance=_structured(raw.get("provenance") or raw.get("source"),"provenance");metadata=_structured(raw.get("metadata"),"metadata")
 requested_security_state=str(raw.get("security_state") or "unscanned").strip().lower()
 if requested_security_state!="unscanned":raise ContentValidationError("security_state is Controller/Agent managed")
 security_state="unscanned"
 base={"mod":"mods","plugin":"plugins","modpack":"modpacks","datapack":"datapacks","map":"maps","workshop":"workshop"}.get(ctype,"assets");target=_target(raw.get("target") or f"{base}/{content}")
 deps=[_token(v,"dependency") for v in (raw.get("dependencies") or [])][:200];conflicts=[_token(v,"conflict") for v in (raw.get("conflicts") or [])][:200]
 identity={"agent_id":agent,"instance_id":instance,"content_id":content,"game_id":game,"content_type":ctype,"desired_state":state,"activation_state":activation_state,"activation_order":activation_order,"version":version,"provider":provider,"target":target,"artifact":artifact,"provenance":provenance,"metadata":metadata,"security_state":security_state,"dependencies":deps,"conflicts":conflicts};checksum=hashlib.sha256(_j(identity).encode()).hexdigest()
 return {"schema_version":2,"kind":"CapivaraContentAssignment",**identity,"checksum":checksum}
__all__=["ContentValidationError","normalize_assignment"]
