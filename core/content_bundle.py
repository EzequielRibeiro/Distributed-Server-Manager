#!/usr/bin/env python3
"""Canonical composed-content bundle contract for Universal Content."""
from __future__ import annotations
import hashlib,json,re
from typing import Any,Mapping

_TOKEN=re.compile(r"^[A-Za-z0-9._:-]{1,191}$")
_SHA256=re.compile(r"^[0-9a-f]{64}$")
_MAX_MANIFEST_BYTES=16*1024*1024
_MAX_MEMBERS=5000
_ALLOWED_LOADERS={"fabric","forge","neoforge","quilt"}

class ContentBundleValidationError(ValueError):pass

def _json(value:Any)->str:return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def _token(value:Any,label:str)->str:
 text=str(value or "").strip()
 if not _TOKEN.fullmatch(text):raise ContentBundleValidationError(f"invalid {label}")
 return text

def _safe_path(value:Any,label:str)->str:
 text=str(value or "").strip().replace("\\","/")
 first=text.split("/",1)[0] if text else ""
 if not text or text.startswith("/") or ":" in first or any(part in {"",".",".."} for part in text.split("/")):raise ContentBundleValidationError(f"invalid {label}")
 return text

def _artifact(raw:Any,manifest_kind:str,parent_id:str,loader_id:str,loader_version:str|None,member_path:str)->dict[str,Any]:
 if not isinstance(raw,Mapping):raise ContentBundleValidationError("bundle member artifact must be an object")
 value=dict(raw);provider=str(value.get("provider") or "").strip().lower()
 if provider=="local":
  member=str(value.get("bundle_member") or "").strip().replace("\\","/")
  if (manifest_kind!="serverpack-local-v1" or value.get("serverpack_child_v1") is not True
      or value.get("ephemeral_upload") is not True or value.get("bundle_parent_content_id")!=parent_id
      or not member.startswith("mods/") or member.count("/")!=1
      or not member.lower().endswith(".jar") or any(x in {"",".",".."} for x in member.split("/"))
      or value.get("url") or value.get("download_url") or value.get("resolved_path")
      or member!=member_path or loader_id!="neoforge"
      or value.get("serverpack_loader")!="neoforge"
      or str(value.get("serverpack_loader_version") or "")!=str(loader_version or "")):
   raise ContentBundleValidationError("invalid local Server Pack member contract")
  sha=str(value.get("sha256") or "").strip().lower()
  if not _SHA256.fullmatch(sha):raise ContentBundleValidationError("Server Pack member SHA256 is required")
  try:size=int(value.get("size_bytes"))
  except (TypeError,ValueError) as exc:raise ContentBundleValidationError("invalid Server Pack member size") from exc
  if size<1 or size>256*1024*1024:raise ContentBundleValidationError("invalid Server Pack member size")
  value["sha256"]=sha;value["size_bytes"]=size;value["provider"]="local"
  return value
 if provider not in {"modrinth","curseforge"}:raise ContentBundleValidationError("unsupported bundle member provider")
 value["provider"]=provider
 url=str(value.get("url") or "").strip()
 if not url.startswith("https://"):raise ContentBundleValidationError("bundle member URL must use HTTPS")
 specs=(("sha512",128),("sha256",64),("sha1",40));present=False
 for key,length in specs:
  digest=str(value.get(key) or "").strip().lower()
  if not digest:continue
  if len(digest)!=length or any(ch not in "0123456789abcdef" for ch in digest):raise ContentBundleValidationError(f"invalid bundle member {key}")
  value[key]=digest;present=True
 if not present:raise ContentBundleValidationError("bundle member requires an integrity hash")
 return value

def normalize_bundle(raw:Mapping[str,Any])->dict[str,Any]:
 if not isinstance(raw,Mapping):raise ContentBundleValidationError("content bundle must be an object")
 provider=str(raw.get("provider") or "").strip().lower()
 if provider not in {"modrinth","curseforge","local"}:raise ContentBundleValidationError("unsupported content bundle provider")
 instance_id=_token(raw.get("instance_id"),"instance_id");parent_content_id=_token(raw.get("parent_content_id"),"parent_content_id")
 project_id=_token(raw.get("provider_project_id"),"provider_project_id");version_id=_token(raw.get("provider_version_id"),"provider_version_id")
 minecraft_version=str(raw.get("minecraft_version") or "").strip()[:64]
 if not minecraft_version:raise ContentBundleValidationError("minecraft_version is required")
 loader_id=str(raw.get("loader_id") or "").strip().lower()
 if loader_id not in _ALLOWED_LOADERS:raise ContentBundleValidationError("unsupported modpack loader")
 loader_version=str(raw.get("loader_version") or "").strip()[:191] or None
 manifest_kind=str(raw.get("manifest_kind") or "").strip().lower()
 if manifest_kind not in {"mrpack-v1","curseforge-v1","serverpack-local-v1"}:raise ContentBundleValidationError("unsupported modpack manifest")
 if (manifest_kind=="serverpack-local-v1")!=(provider=="local"):raise ContentBundleValidationError("Server Pack requires the local provider and dedicated manifest")
 members_raw=raw.get("members")
 if not isinstance(members_raw,list) or not members_raw or len(members_raw)>_MAX_MEMBERS:raise ContentBundleValidationError("invalid modpack member list")
 if manifest_kind=="serverpack-local-v1" and len(members_raw)>1500:raise ContentBundleValidationError("Server Pack exceeds 1500 managed mods")
 members=[];seen=set()
 for index,item in enumerate(members_raw):
  if not isinstance(item,Mapping):raise ContentBundleValidationError("invalid modpack member")
  content_id=_token(item.get("content_id"),"bundle member content_id");path=_safe_path(item.get("path"),"modpack member path")
  if path in seen:raise ContentBundleValidationError("duplicate modpack member path")
  seen.add(path);members.append({"index":index,"content_id":content_id,"path":path,"required":bool(item.get("required",True)),"artifact":_artifact(item.get("artifact"),manifest_kind,parent_content_id,loader_id,loader_version,path)})
 roots=[]
 for value in raw.get("override_roots") or []:
  root=_safe_path(value,"override root")
  if "/" in root:raise ContentBundleValidationError("override root must be a top-level directory")
  if root not in roots:roots.append(root)
 if len(roots)>8:raise ContentBundleValidationError("too many override roots")
 manifest={"schema_version":1,"kind":"CapivaraMinecraftModpackManifest","provider":provider,"provider_project_id":project_id,"provider_version_id":version_id,"minecraft_version":minecraft_version,"loader":{"id":loader_id,"version":loader_version},"manifest_kind":manifest_kind,"members":members,"override_roots":roots}
 encoded=_json(manifest).encode("utf-8")
 if len(encoded)>_MAX_MANIFEST_BYTES:raise ContentBundleValidationError("modpack manifest exceeds maximum size")
 manifest_sha256=hashlib.sha256(encoded).hexdigest();supplied=str(raw.get("manifest_sha256") or "").strip().lower()
 if supplied and (not _SHA256.fullmatch(supplied) or supplied!=manifest_sha256):raise ContentBundleValidationError("modpack manifest checksum mismatch")
 identity={"instance_id":instance_id,"parent_content_id":parent_content_id,"provider":provider,"provider_project_id":project_id,"provider_version_id":version_id,"minecraft_version":minecraft_version,"loader_id":loader_id,"loader_version":loader_version,"manifest_kind":manifest_kind,"manifest_sha256":manifest_sha256,"override_roots":roots}
 checksum=hashlib.sha256(_json(identity).encode("utf-8")).hexdigest()
 return {"schema_version":1,"kind":"CapivaraContentBundle",**identity,"manifest":manifest,"checksum":checksum}

__all__=["ContentBundleValidationError","normalize_bundle"]
