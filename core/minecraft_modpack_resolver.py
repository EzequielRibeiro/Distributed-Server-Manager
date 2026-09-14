#!/usr/bin/env python3
"""Controller-side Minecraft modpack resolution into canonical UCP bundles."""
from __future__ import annotations
import hashlib,io,json,stat,zipfile
from pathlib import Path
from typing import Any,Callable,Mapping
from urllib.parse import quote,urlencode,urlparse
from urllib.request import Request,urlopen
from minecraft_content_resolver import CURSEFORGE_API_BASE,CURSEFORGE_MINECRAFT_GAME_ID,MODRINTH_API_BASE,MinecraftContentResolverError,provider_loaders,_request_json,_secret_file

JsonRequester=Callable[[str,Mapping[str,str]],Any]
BytesRequester=Callable[[str,Mapping[str,str],int],bytes]
_MAX_PACK_BYTES=256*1024*1024;_MAX_ARCHIVE_ENTRIES=20000;_MAX_ARCHIVE_EXPANDED=4*1024*1024*1024;_MAX_MANIFEST_BYTES=16*1024*1024
_MODRINTH_DOWNLOAD_HOSTS={"cdn.modrinth.com","github.com","raw.githubusercontent.com","gitlab.com"}

def _request_bytes(url:str,headers:Mapping[str,str],limit:int=_MAX_PACK_BYTES)->bytes:
 req=Request(url,headers={"User-Agent":"Capivara-DSM/2",**dict(headers)})
 with urlopen(req,timeout=60) as response:
  data=response.read(limit+1)
 if len(data)>limit:raise MinecraftContentResolverError("modpack archive exceeds Controller safety limit")
 return data

def _safe_relative(value:Any,label:str)->str:
 text=str(value or "").strip().replace("\\","/");first=text.split("/",1)[0] if text else ""
 if not text or text.startswith("/") or ":" in first or any(part in {"",".",".."} for part in text.split("/")):raise MinecraftContentResolverError(f"unsafe {label}")
 return text

def _https_url(value:Any,label:str,hosts:set[str]|None=None)->str:
 text=str(value or "").strip();parsed=urlparse(text)
 if parsed.scheme!="https" or not parsed.hostname or parsed.username or parsed.password:raise MinecraftContentResolverError(f"{label} must use HTTPS")
 if hosts is not None and parsed.hostname.lower() not in hosts:raise MinecraftContentResolverError(f"{label} host is not allowlisted")
 return text

def _verify_bytes(data:bytes,artifact:Mapping[str,Any])->None:
 for key,factory,length in (("sha512",hashlib.sha512,128),("sha256",hashlib.sha256,64),("sha1",hashlib.sha1,40)):
  expected=str(artifact.get(key) or "").strip().lower()
  if not expected:continue
  if len(expected)!=length or factory(data).hexdigest()!=expected:raise MinecraftContentResolverError(f"modpack archive {key} mismatch")

def _zip(blob:bytes)->zipfile.ZipFile:
 try:handle=zipfile.ZipFile(io.BytesIO(blob))
 except zipfile.BadZipFile as exc:raise MinecraftContentResolverError("modpack artifact is not a valid ZIP archive") from exc
 entries=handle.infolist()
 if len(entries)>_MAX_ARCHIVE_ENTRIES:handle.close();raise MinecraftContentResolverError("modpack archive has too many entries")
 total=0
 for item in entries:
  archive_name=str(item.filename or "").rstrip("/")
  if not archive_name:handle.close();raise MinecraftContentResolverError("modpack archive contains an empty path")
  _safe_relative(archive_name,"modpack archive path");total+=max(0,int(item.file_size or 0));mode=(item.external_attr>>16)&0xFFFF
  if stat.S_ISLNK(mode):handle.close();raise MinecraftContentResolverError("modpack archive contains a symbolic link")
  if total>_MAX_ARCHIVE_EXPANDED:handle.close();raise MinecraftContentResolverError("modpack archive expands beyond safety limit")
 return handle

def _json_member(handle:zipfile.ZipFile,name:str)->dict[str,Any]:
 try:info=handle.getinfo(name)
 except KeyError as exc:raise MinecraftContentResolverError(f"modpack archive is missing {name}") from exc
 if info.file_size>_MAX_MANIFEST_BYTES:raise MinecraftContentResolverError("modpack manifest exceeds maximum size")
 try:value=json.loads(handle.read(info).decode("utf-8"))
 except (UnicodeDecodeError,json.JSONDecodeError) as exc:raise MinecraftContentResolverError("modpack manifest is invalid JSON") from exc
 if not isinstance(value,dict):raise MinecraftContentResolverError("modpack manifest must be an object")
 return value

def _loader(runtime:Mapping[str,Any])->str:
 loaders=provider_loaders(runtime,"mod")
 if len(loaders)!=1:raise MinecraftContentResolverError("modpack runtime loader is ambiguous")
 return loaders[0]

def _loader_dependency(loader:str)->str:return {"fabric":"fabric-loader","forge":"forge","neoforge":"neoforge","quilt":"quilt-loader"}[loader]
def _child_id(parent_content_id:str,path:str)->str:return "mb-"+hashlib.sha256((str(parent_content_id)+"\0"+path).encode()).hexdigest()[:32]
def _rank(item:Mapping[str,Any])->tuple[int,str]:return ({"release":3,"beta":2,"alpha":1}.get(str(item.get("version_type") or "").lower(),0),str(item.get("date_published") or item.get("fileDate") or ""))

def _modrinth_parent(project:str,game_version:str,loader:str,requester:JsonRequester)->tuple[dict[str,Any],dict[str,Any],dict[str,Any]]:
 ref=str(project or "").strip()
 if not ref or any(ch in ref for ch in ("/","\\","?","#")):raise MinecraftContentResolverError("invalid Modrinth modpack reference")
 encoded=quote(ref,safe="");project_data=requester(f"{MODRINTH_API_BASE}/project/{encoded}",{})
 if not isinstance(project_data,Mapping) or str(project_data.get("project_type") or "").lower()!="modpack":raise MinecraftContentResolverError("Modrinth project is not a modpack")
 if str(project_data.get("status") or "unknown").lower() not in {"approved","archived"}:raise MinecraftContentResolverError("Modrinth modpack is not available")
 query=urlencode({"game_versions":json.dumps([game_version]),"loaders":json.dumps([loader]),"include_changelog":"false"});versions=requester(f"{MODRINTH_API_BASE}/project/{encoded}/version?{query}",{})
 compatible=[item for item in (versions if isinstance(versions,list) else []) if isinstance(item,Mapping) and game_version in (item.get("game_versions") or []) and loader in (item.get("loaders") or []) and str(item.get("status") or "listed") in {"listed","unknown"}]
 if not compatible:raise MinecraftContentResolverError("no compatible Modrinth modpack version")
 version=sorted(compatible,key=_rank,reverse=True)[0];files=[f for f in version.get("files") or [] if isinstance(f,Mapping)]
 file=next((f for f in files if str(f.get("filename") or "").lower().endswith(".mrpack") and f.get("primary") is True),next((f for f in files if str(f.get("filename") or "").lower().endswith(".mrpack")),None))
 if not isinstance(file,Mapping):raise MinecraftContentResolverError("Modrinth modpack version has no .mrpack artifact")
 hashes=file.get("hashes") if isinstance(file.get("hashes"),Mapping) else {};sha512=str(hashes.get("sha512") or "").strip().lower();sha1=str(hashes.get("sha1") or "").strip().lower()
 if len(sha512)!=128 or len(sha1)!=40:raise MinecraftContentResolverError("Modrinth modpack artifact requires SHA-512 and SHA-1")
 project_id=str(version.get("project_id") or project_data.get("id") or ref);version_id=str(version.get("id") or "")
 if not version_id:raise MinecraftContentResolverError("Modrinth modpack version identity is missing")
 artifact={"provider":"modrinth","package_id":f"{project_id}:{version_id}","url":_https_url(file.get("url"),"Modrinth modpack URL",_MODRINTH_DOWNLOAD_HOSTS),"filename":str(file.get("filename") or "pack.mrpack"),"sha512":sha512,"sha1":sha1,"archive":True}
 if file.get("size") is not None:artifact["size_bytes"]=int(file["size"])
 return dict(project_data),dict(version),artifact

def resolve_modrinth_modpack(project:str,parent_content_id:str,game_version:str,runtime:Mapping[str,Any],*,requester:JsonRequester=_request_json,bytes_requester:BytesRequester=_request_bytes)->dict[str,Any]:
 loader=_loader(runtime);project_data,version,parent_artifact=_modrinth_parent(project,game_version,loader,requester);blob=bytes_requester(parent_artifact["url"],{},_MAX_PACK_BYTES);_verify_bytes(blob,parent_artifact)
 with _zip(blob) as handle:
  index=_json_member(handle,"modrinth.index.json");names={item.filename.split("/",1)[0] for item in handle.infolist() if "/" in item.filename}
 if int(index.get("formatVersion") or 0)!=1 or str(index.get("game") or "").lower()!="minecraft":raise MinecraftContentResolverError("unsupported Modrinth modpack format")
 deps=index.get("dependencies") if isinstance(index.get("dependencies"),Mapping) else {}
 if str(deps.get("minecraft") or "")!=game_version:raise MinecraftContentResolverError("Modrinth modpack Minecraft version does not match the instance")
 loader_version=str(deps.get(_loader_dependency(loader)) or "").strip()
 if not loader_version:raise MinecraftContentResolverError("Modrinth modpack loader does not match the instance runtime")
 members=[];children=[]
 for item in index.get("files") or []:
  if not isinstance(item,Mapping):raise MinecraftContentResolverError("invalid Modrinth modpack file entry")
  env=item.get("env") if isinstance(item.get("env"),Mapping) else {};server=str(env.get("server") or "required").lower()
  if server=="unsupported" or server=="optional":continue
  if server!="required":raise MinecraftContentResolverError("invalid Modrinth server environment flag")
  path=_safe_relative(item.get("path"),"Modrinth modpack file path")
  if not path.startswith("mods/") or not path.lower().endswith(".jar"):raise MinecraftContentResolverError("server-required Modrinth pack file is outside managed mods/")
  hashes=item.get("hashes") if isinstance(item.get("hashes"),Mapping) else {};sha512=str(hashes.get("sha512") or "").strip().lower();sha1=str(hashes.get("sha1") or "").strip().lower()
  if len(sha512)!=128 or len(sha1)!=40:raise MinecraftContentResolverError("Modrinth pack member requires SHA-512 and SHA-1")
  downloads=item.get("downloads") if isinstance(item.get("downloads"),list) else [];url=next((_https_url(v,"Modrinth pack member URL",_MODRINTH_DOWNLOAD_HOSTS) for v in downloads if str(v).startswith("https://")),None)
  if not url:raise MinecraftContentResolverError("Modrinth pack member has no allowlisted download URL")
  cid=_child_id(parent_content_id,path);artifact={"provider":"modrinth","package_id":f"{version.get('id')}:{cid}","url":url,"filename":Path(path).name,"sha512":sha512,"sha1":sha1}
  if item.get("fileSize") is not None:artifact["size_bytes"]=int(item["fileSize"])
  members.append({"content_id":cid,"path":path,"required":True,"artifact":artifact});children.append({"content_id":cid,"content_type":"mod","provider":"modrinth","version":str(version.get("version_number") or version.get("id")),"artifact":artifact,"target":f"mods/{cid}","provenance":{"bundle_provider":"modrinth","bundle_project_id":str(version.get("project_id") or project_data.get("id")),"bundle_version_id":str(version.get("id")),"bundle_path":path}})
 if not members:raise MinecraftContentResolverError("Modrinth modpack has no server-required managed mods")
 roots=[root for root in ("overrides","server-overrides") if root in names]
 return {"parent":{"version":str(version.get("version_number") or version.get("id")),"artifact":parent_artifact,"provenance":{"provider":"modrinth","project_id":str(version.get("project_id") or project_data.get("id")),"version_id":str(version.get("id"))}},"bundle":{"provider":"modrinth","provider_project_id":str(version.get("project_id") or project_data.get("id")),"provider_version_id":str(version.get("id")),"minecraft_version":game_version,"loader_id":loader,"loader_version":loader_version,"manifest_kind":"mrpack-v1","members":members,"override_roots":roots},"children":children}

def _curseforge_classes(key:str,requester:JsonRequester)->tuple[set[int],set[int]]:
 payload=requester(f"{CURSEFORGE_API_BASE}/categories?{urlencode({'gameId':CURSEFORGE_MINECRAFT_GAME_ID,'classesOnly':'true'})}",{"x-api-key":key});rows=payload.get("data") if isinstance(payload,Mapping) else []
 mods=set();packs=set()
 for item in rows or []:
  if not isinstance(item,Mapping) or not bool(item.get("isClass")):continue
  text=(str(item.get("slug") or "")+" "+str(item.get("name") or "")).lower();ident=int(item.get("id") or 0)
  if "modpack" in text:packs.add(ident)
  elif text.strip() in {"mods mods","mc-mods mods"} or str(item.get("name") or "").strip().lower()=="mods":mods.add(ident)
 return mods,packs

def _cf_sha1(file:Mapping[str,Any])->str:
 for item in file.get("hashes") or []:
  if isinstance(item,Mapping) and int(item.get("algo") or 0)==1:
   value=str(item.get("value") or "").strip().lower()
   if len(value)==40:return value
 raise MinecraftContentResolverError("CurseForge file is missing SHA-1")

def _cf_download(mod_id:int,file:Mapping[str,Any],key:str,requester:JsonRequester)->str:
 url=str(file.get("downloadUrl") or "").strip();file_id=int(file.get("id") or 0)
 if not url:
  payload=requester(f"{CURSEFORGE_API_BASE}/mods/{mod_id}/files/{file_id}/download-url",{"x-api-key":key});url=str(payload.get("data") if isinstance(payload,Mapping) else "")
 return _https_url(url,"CurseForge download URL")

def resolve_curseforge_modpack(project:str,parent_content_id:str,game_version:str,runtime:Mapping[str,Any],*,api_key:str|None=None,api_key_file:str|None=None,requester:JsonRequester=_request_json,bytes_requester:BytesRequester=_request_bytes)->dict[str,Any]:
 try:mod_id=int(str(project).strip())
 except (TypeError,ValueError) as exc:raise MinecraftContentResolverError("CurseForge modpack reference must be numeric") from exc
 key=str(api_key or "").strip() or _secret_file(api_key_file);headers={"x-api-key":key};loader=_loader(runtime);mod_classes,pack_classes=_curseforge_classes(key,requester)
 project_payload=requester(f"{CURSEFORGE_API_BASE}/mods/{mod_id}",headers);project_data=project_payload.get("data") if isinstance(project_payload,Mapping) else None
 if not isinstance(project_data,Mapping) or int(project_data.get("gameId") or 0)!=CURSEFORGE_MINECRAFT_GAME_ID or int(project_data.get("classId") or 0) not in pack_classes:raise MinecraftContentResolverError("CurseForge project is not a Minecraft modpack")
 files_payload=requester(f"{CURSEFORGE_API_BASE}/mods/{mod_id}/files?{urlencode({'gameVersion':game_version,'pageSize':50})}",headers);files=files_payload.get("data") if isinstance(files_payload,Mapping) else []
 compatible=[f for f in files or [] if isinstance(f,Mapping) and bool(f.get("isAvailable",True)) and game_version in (f.get("gameVersions") or []) and str(f.get("fileName") or "").lower().endswith(".zip")]
 if not compatible:raise MinecraftContentResolverError("no compatible CurseForge modpack file")
 file=sorted(compatible,key=lambda v:(1 if int(v.get("releaseType") or 0)==1 else 0,str(v.get("fileDate") or "")),reverse=True)[0];file_id=int(file.get("id") or 0);parent_artifact={"provider":"curseforge","package_id":f"{mod_id}:{file_id}","url":_cf_download(mod_id,file,key,requester),"filename":str(file.get("fileName") or f"{file_id}.zip"),"sha1":_cf_sha1(file),"archive":True}
 if file.get("fileLength") is not None:parent_artifact["size_bytes"]=int(file["fileLength"])
 blob=bytes_requester(parent_artifact["url"],{},_MAX_PACK_BYTES);_verify_bytes(blob,parent_artifact)
 with _zip(blob) as handle:manifest=_json_member(handle,"manifest.json");top={item.filename.split("/",1)[0] for item in handle.infolist() if "/" in item.filename}
 if str(manifest.get("manifestType") or "")!="minecraftModpack" or int(manifest.get("manifestVersion") or 0)!=1:raise MinecraftContentResolverError("unsupported CurseForge modpack manifest")
 minecraft=manifest.get("minecraft") if isinstance(manifest.get("minecraft"),Mapping) else {}
 if str(minecraft.get("version") or "")!=game_version:raise MinecraftContentResolverError("CurseForge modpack Minecraft version does not match the instance")
 loaders=[v for v in minecraft.get("modLoaders") or [] if isinstance(v,Mapping)];primary=next((v for v in loaders if v.get("primary") is True),loaders[0] if loaders else None)
 if not isinstance(primary,Mapping):raise MinecraftContentResolverError("CurseForge modpack has no mod loader")
 raw_loader=str(primary.get("id") or "").strip();prefix=loader+"-"
 if not raw_loader.lower().startswith(prefix):raise MinecraftContentResolverError("CurseForge modpack loader does not match the instance runtime")
 loader_version=raw_loader[len(prefix):]
 if not loader_version:raise MinecraftContentResolverError("CurseForge modpack loader version is missing")
 members=[];children=[]
 for index,entry in enumerate(manifest.get("files") or []):
  if not isinstance(entry,Mapping):raise MinecraftContentResolverError("invalid CurseForge modpack member")
  if not bool(entry.get("required",True)):continue
  project_id=int(entry.get("projectID") or 0);child_file_id=int(entry.get("fileID") or 0)
  if project_id<=0 or child_file_id<=0:raise MinecraftContentResolverError("invalid CurseForge modpack file reference")
  cp=requester(f"{CURSEFORGE_API_BASE}/mods/{project_id}",headers);cd=cp.get("data") if isinstance(cp,Mapping) else None
  if not isinstance(cd,Mapping) or int(cd.get("gameId") or 0)!=CURSEFORGE_MINECRAFT_GAME_ID or int(cd.get("classId") or 0) not in mod_classes:raise MinecraftContentResolverError("CurseForge modpack member is not a Minecraft mod")
  fp=requester(f"{CURSEFORGE_API_BASE}/mods/{project_id}/files/{child_file_id}",headers);fd=fp.get("data") if isinstance(fp,Mapping) else None
  if not isinstance(fd,Mapping) or int(fd.get("id") or 0)!=child_file_id or not bool(fd.get("isAvailable",True)):raise MinecraftContentResolverError("CurseForge modpack member file is unavailable")
  versions=[str(v).lower() for v in fd.get("gameVersions") or []]
  if game_version.lower() not in versions or loader not in versions:raise MinecraftContentResolverError("CurseForge modpack member is incompatible with runtime")
  filename=str(fd.get("fileName") or "").strip()
  if not filename.lower().endswith(".jar"):raise MinecraftContentResolverError("CurseForge modpack member is not a JAR mod")
  path=f"mods/{filename}";cid=_child_id(parent_content_id,path);artifact={"provider":"curseforge","package_id":f"{project_id}:{child_file_id}","url":_cf_download(project_id,fd,key,requester),"filename":filename,"sha1":_cf_sha1(fd)}
  if fd.get("fileLength") is not None:artifact["size_bytes"]=int(fd["fileLength"])
  members.append({"content_id":cid,"path":path,"required":True,"artifact":artifact});children.append({"content_id":cid,"content_type":"mod","provider":"curseforge","version":str(fd.get("displayName") or child_file_id),"artifact":artifact,"target":f"mods/{cid}","provenance":{"bundle_provider":"curseforge","bundle_project_id":str(mod_id),"bundle_file_id":str(file_id),"project_id":str(project_id),"file_id":str(child_file_id)}})
 if not members:raise MinecraftContentResolverError("CurseForge modpack has no required managed mods")
 override=str(manifest.get("overrides") or "overrides").strip();override=_safe_relative(override,"CurseForge override root")
 if "/" in override:raise MinecraftContentResolverError("CurseForge override root must be top-level")
 roots=[override] if override in top else []
 return {"parent":{"version":str(file.get("displayName") or file_id),"artifact":parent_artifact,"provenance":{"provider":"curseforge","project_id":str(mod_id),"file_id":str(file_id)}},"bundle":{"provider":"curseforge","provider_project_id":str(mod_id),"provider_version_id":str(file_id),"minecraft_version":game_version,"loader_id":loader,"loader_version":loader_version,"manifest_kind":"curseforge-v1","members":members,"override_roots":roots},"children":children}

def resolve_minecraft_modpack(provider:str,project:str,parent_content_id:str,game_version:str,runtime:Mapping[str,Any],**kwargs)->dict[str,Any]:
 provider=str(provider or "").strip().lower()
 if provider=="modrinth":return resolve_modrinth_modpack(project,parent_content_id,game_version,runtime,requester=kwargs.get("requester",_request_json),bytes_requester=kwargs.get("bytes_requester",_request_bytes))
 if provider=="curseforge":return resolve_curseforge_modpack(project,parent_content_id,game_version,runtime,api_key=kwargs.get("curseforge_api_key"),api_key_file=kwargs.get("curseforge_api_key_file"),requester=kwargs.get("requester",_request_json),bytes_requester=kwargs.get("bytes_requester",_request_bytes))
 raise MinecraftContentResolverError("unsupported Minecraft modpack provider")

__all__=["resolve_curseforge_modpack","resolve_minecraft_modpack","resolve_modrinth_modpack"]
