#!/usr/bin/env python3
"""Canonical desired-state contract for Capivara Universal Content."""
from __future__ import annotations
import hashlib,json,re
from typing import Any,Mapping
_TOKEN=re.compile(r"^[A-Za-z0-9._:-]{1,191}$")
_TYPES={"mod","plugin","modpack","map","asset","workshop","other"};_STATES={"installed","absent"};_PROVIDERS={"steam","http","http-archive","github","modrinth","local","custom","source-build"}
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
def normalize_assignment(raw:Mapping[str,Any],*,expected_agent_id:str|None=None)->dict[str,Any]:
 if not isinstance(raw,Mapping):raise ContentValidationError("content assignment must be an object")
 agent=_token(raw.get("agent_id") or expected_agent_id,"agent_id")
 if expected_agent_id and agent!=expected_agent_id:raise ContentValidationError("Agent identity mismatch")
 instance=_token(raw.get("instance_id"),"instance_id");content=_token(raw.get("content_id"),"content_id");game=_token(raw.get("game_id"),"game_id").lower();ctype=str(raw.get("content_type") or "other").strip().lower()
 if ctype not in _TYPES:raise ContentValidationError("invalid content_type")
 state=str(raw.get("desired_state") or "installed").strip().lower()
 if state not in _STATES:raise ContentValidationError("invalid desired_state")
 version=str(raw.get("version") or "latest").strip()[:191] or "latest";provider=str(raw.get("provider") or (raw.get("artifact") or {}).get("provider") or "").strip().lower()
 if provider not in _PROVIDERS:raise ContentValidationError("invalid provider")
 artifact=dict(raw.get("artifact") or {})
 if any(k in artifact for k in ("command","shell","exec","script")):raise ContentValidationError("artifact may not contain executable commands")
 artifact["provider"]=provider;base={"mod":"mods","plugin":"plugins","modpack":"modpacks","map":"maps","workshop":"workshop"}.get(ctype,"assets");target=_target(raw.get("target") or f"{base}/{content}")
 deps=[_token(v,"dependency") for v in (raw.get("dependencies") or [])][:200];conflicts=[_token(v,"conflict") for v in (raw.get("conflicts") or [])][:200]
 identity={"agent_id":agent,"instance_id":instance,"content_id":content,"game_id":game,"content_type":ctype,"desired_state":state,"version":version,"provider":provider,"target":target,"artifact":artifact,"dependencies":deps,"conflicts":conflicts};checksum=hashlib.sha256(_j(identity).encode()).hexdigest()
 return {"schema_version":1,"kind":"CapivaraContentAssignment",**identity,"checksum":checksum}
__all__=["ContentValidationError","normalize_assignment"]
