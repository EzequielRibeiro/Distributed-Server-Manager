#!/usr/bin/env python3
"""Canonical contracts for D2 Real-Time & API Platform."""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import re
import secrets
from typing import Any,Iterable

_SCOPE=re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")
ALLOWED_SCOPES={
 "events:read","observability:read","instances:read","broadcasts:write","automation:write","realtime:read","api:admin"
}
DEFAULT_READ_SCOPES=("events:read","observability:read","instances:read","realtime:read")
class ApiValidationError(ValueError):pass

def normalize_scopes(raw:Iterable[Any]|None)->list[str]:
 scopes=[]
 for value in raw or []:
  scope=str(value or "").strip().lower()
  if not _SCOPE.fullmatch(scope) or scope not in ALLOWED_SCOPES:raise ApiValidationError(f"invalid API scope: {scope or '<empty>'}")
  if scope not in scopes:scopes.append(scope)
 if not scopes:scopes=list(DEFAULT_READ_SCOPES)
 return sorted(scopes)

def issue_secret(token_id:str)->tuple[str,str,str]:
 short=re.sub(r"[^a-zA-Z0-9]","",str(token_id))[:12]
 if len(short)<8:raise ApiValidationError("invalid token_id")
 secret=secrets.token_urlsafe(32);prefix=f"capv2_{short}";presented=f"{prefix}_{secret}"
 return prefix,presented,hash_secret(secret)

def hash_secret(secret:str)->str:return hashlib.sha256(str(secret).encode("utf-8")).hexdigest()
def verify_secret(secret:str,digest:str)->bool:return hmac.compare_digest(hash_secret(secret),str(digest or ""))
def split_token(value:str)->tuple[str,str]:
 text=str(value or "").strip()
 if not text.startswith("capv2_"):raise ApiValidationError("invalid bearer token")
 rest=text[len("capv2_"):]
 if "_" not in rest:raise ApiValidationError("invalid bearer token")
 short,secret=rest.split("_",1)
 prefix=f"capv2_{short}"
 if len(short)<8 or not short.isalnum() or not secret:raise ApiValidationError("invalid bearer token")
 return prefix,secret

def encode_cursor(occurred_at:str,event_id:str)->str:
 payload=json.dumps({"t":str(occurred_at),"e":str(event_id)},separators=(",",":"),sort_keys=True).encode()
 return base64.urlsafe_b64encode(payload).decode().rstrip("=")
def decode_cursor(value:str|None)->tuple[str,str]|None:
 if not value:return None
 try:
  raw=str(value);raw+="="*((4-len(raw)%4)%4);obj=json.loads(base64.urlsafe_b64decode(raw.encode()).decode())
  t=str(obj["t"]);e=str(obj["e"])
  if not t or not e:raise ValueError
  return t,e
 except Exception as exc:raise ApiValidationError("invalid realtime cursor") from exc

def has_scope(principal:dict[str,Any],scope:str)->bool:
 scopes={str(x) for x in principal.get("scopes") or []}
 return "api:admin" in scopes or scope in scopes

__all__=["ALLOWED_SCOPES","DEFAULT_READ_SCOPES","ApiValidationError","decode_cursor","encode_cursor","has_scope","issue_secret","normalize_scopes","split_token","verify_secret"]
