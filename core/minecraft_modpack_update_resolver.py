#!/usr/bin/env python3
"""Lightweight provider revision discovery for managed Minecraft modpacks.

This intentionally resolves only the immutable provider revision identity. The
full archive/manifests are downloaded and validated by minecraft_modpack_resolver
only when an update is actually applied.
"""
from __future__ import annotations
import json
from typing import Any,Callable,Mapping
from urllib.parse import quote,urlencode
from minecraft_content_resolver import CURSEFORGE_API_BASE,CURSEFORGE_MINECRAFT_GAME_ID,MODRINTH_API_BASE,MinecraftContentResolverError,_request_json,_secret_file,provider_loaders

Requester=Callable[[str,Mapping[str,str]],Any]


def _loader(runtime:Mapping[str,Any])->str:
 values=provider_loaders(runtime,'mod')
 if len(values)!=1:raise MinecraftContentResolverError('modpack runtime loader is ambiguous')
 return values[0]


def _rank_modrinth(item:Mapping[str,Any])->tuple[int,str]:
 return ({'release':3,'beta':2,'alpha':1}.get(str(item.get('version_type') or '').lower(),0),str(item.get('date_published') or ''))


def resolve_modrinth_modpack_update(project:str,game_version:str,runtime:Mapping[str,Any],*,requester:Requester=_request_json)->dict[str,str]:
 ref=str(project or '').strip()
 if not ref or any(char in ref for char in ('/','\\','?','#')):raise MinecraftContentResolverError('invalid Modrinth modpack reference')
 loader=_loader(runtime);encoded=quote(ref,safe='');project_data=requester(f'{MODRINTH_API_BASE}/project/{encoded}',{})
 if not isinstance(project_data,Mapping) or str(project_data.get('project_type') or '').lower()!='modpack':raise MinecraftContentResolverError('Modrinth project is not a modpack')
 if str(project_data.get('status') or 'unknown').lower() not in {'approved','archived'}:raise MinecraftContentResolverError('Modrinth modpack is not available')
 query=urlencode({'game_versions':json.dumps([game_version]),'loaders':json.dumps([loader]),'include_changelog':'false'});payload=requester(f'{MODRINTH_API_BASE}/project/{encoded}/version?{query}',{})
 compatible=[item for item in (payload if isinstance(payload,list) else []) if isinstance(item,Mapping) and game_version in (item.get('game_versions') or []) and loader in (item.get('loaders') or []) and str(item.get('status') or 'listed') in {'listed','unknown'}]
 if not compatible:raise MinecraftContentResolverError('no compatible Modrinth modpack version')
 version=sorted(compatible,key=_rank_modrinth,reverse=True)[0];project_id=str(version.get('project_id') or project_data.get('id') or ref).strip();revision=str(version.get('id') or '').strip()
 if not project_id or not revision:raise MinecraftContentResolverError('Modrinth modpack revision identity is missing')
 return {'provider':'modrinth','project_id':project_id,'revision':revision,'package_id':f'{project_id}:{revision}'}


def _curseforge_pack_classes(key:str,requester:Requester)->set[int]:
 payload=requester(f"{CURSEFORGE_API_BASE}/categories?{urlencode({'gameId':CURSEFORGE_MINECRAFT_GAME_ID,'classesOnly':'true'})}",{'x-api-key':key});rows=payload.get('data') if isinstance(payload,Mapping) else [];result=set()
 for item in rows or []:
  if not isinstance(item,Mapping) or not bool(item.get('isClass')):continue
  text=(str(item.get('slug') or '')+' '+str(item.get('name') or '')).lower()
  if 'modpack' in text:
   ident=int(item.get('id') or 0)
   if ident>0:result.add(ident)
 return result


def resolve_curseforge_modpack_update(project:str,game_version:str,runtime:Mapping[str,Any],*,api_key:str|None=None,api_key_file:str|None=None,requester:Requester=_request_json)->dict[str,str]:
 try:mod_id=int(str(project).strip())
 except (TypeError,ValueError) as exc:raise MinecraftContentResolverError('CurseForge modpack reference must be numeric') from exc
 if mod_id<=0:raise MinecraftContentResolverError('invalid CurseForge modpack id')
 _loader(runtime);key=str(api_key or '').strip() or _secret_file(api_key_file);headers={'x-api-key':key};pack_classes=_curseforge_pack_classes(key,requester);project_payload=requester(f'{CURSEFORGE_API_BASE}/mods/{mod_id}',headers);project_data=project_payload.get('data') if isinstance(project_payload,Mapping) else None
 if not isinstance(project_data,Mapping) or int(project_data.get('gameId') or 0)!=CURSEFORGE_MINECRAFT_GAME_ID or int(project_data.get('classId') or 0) not in pack_classes:raise MinecraftContentResolverError('CurseForge project is not a Minecraft modpack')
 files_payload=requester(f"{CURSEFORGE_API_BASE}/mods/{mod_id}/files?{urlencode({'gameVersion':game_version,'pageSize':50})}",headers);files=files_payload.get('data') if isinstance(files_payload,Mapping) else []
 compatible=[item for item in files or [] if isinstance(item,Mapping) and bool(item.get('isAvailable',True)) and game_version in (item.get('gameVersions') or []) and str(item.get('fileName') or '').lower().endswith('.zip')]
 if not compatible:raise MinecraftContentResolverError('no compatible CurseForge modpack file')
 file=sorted(compatible,key=lambda value:(1 if int(value.get('releaseType') or 0)==1 else 0,str(value.get('fileDate') or '')),reverse=True)[0];revision=str(int(file.get('id') or 0))
 if revision=='0':raise MinecraftContentResolverError('CurseForge modpack revision identity is missing')
 return {'provider':'curseforge','project_id':str(mod_id),'revision':revision,'package_id':f'{mod_id}:{revision}'}


def resolve_minecraft_modpack_update(provider:str,project:str,game_version:str,runtime:Mapping[str,Any],**kwargs)->dict[str,str]:
 value=str(provider or '').strip().lower()
 if value=='modrinth':return resolve_modrinth_modpack_update(project,game_version,runtime,requester=kwargs.get('requester',_request_json))
 if value=='curseforge':return resolve_curseforge_modpack_update(project,game_version,runtime,api_key=kwargs.get('curseforge_api_key'),api_key_file=kwargs.get('curseforge_api_key_file'),requester=kwargs.get('requester',_request_json))
 raise MinecraftContentResolverError('unsupported Minecraft modpack provider')


__all__=['resolve_curseforge_modpack_update','resolve_minecraft_modpack_update','resolve_modrinth_modpack_update']
