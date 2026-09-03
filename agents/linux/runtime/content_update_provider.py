#!/usr/bin/env python3
"""Game-neutral upstream update detection for managed content."""
from __future__ import annotations
import json,re,time,urllib.parse,urllib.request
from pathlib import Path
from typing import Any,Callable
_TOKEN=re.compile(r'^([0-9]+):([0-9]+)$')
_TIME_UPDATED=re.compile(r'"timeupdated"\s+"(\d+)"',re.I)
_CACHE:dict[str,tuple[float,str]]={}

def parse_workshop_package(value:Any)->tuple[str,str]:
 text=str(value or '').strip();match=_TOKEN.fullmatch(text)
 if not match:raise ValueError('invalid Steam Workshop package; expected AppID:PublishedFileId')
 return match.group(1),match.group(2)

def parse_workshop_manifest(text:str,item_id:str)->str|None:
 item=str(item_id or '').strip()
 if not item.isdigit():raise ValueError('invalid PublishedFileId')
 lines=str(text or '').splitlines();inside=False;depth=0;pending=False
 for raw in lines:
  s=raw.strip()
  if not inside and s==f'"{item}"':pending=True;continue
  if pending and not inside:
   if s=='{':inside=True;depth=1;pending=False
   elif s:pending=False
   continue
  if inside:
   depth+=s.count('{')-s.count('}')
   match=_TIME_UPDATED.search(s)
   if match:return match.group(1)
   if depth<=0:return None
 return None

def _manifest_candidates(state_root:Path,app_id:str)->list[Path]:
 name=f'appworkshop_{app_id}.acf';home=Path.home()
 return [state_root/'tools/steamcmd/steamapps/workshop'/name,home/'.steam/steam/steamapps/workshop'/name,home/'.local/share/Steam/steamapps/workshop'/name]

def installed_workshop_revision(state_root:Path,package_id:str)->str|None:
 app_id,item_id=parse_workshop_package(package_id)
 for path in _manifest_candidates(state_root,app_id):
  try:value=parse_workshop_manifest(path.read_text(encoding='utf-8',errors='replace'),item_id)
  except OSError:continue
  if value:return value
 return None

def upstream_workshop_revision(package_id:str,*,ttl:int=300,opener:Callable[...,Any]=urllib.request.urlopen,force_refresh:bool=False)->str:
 _,item_id=parse_workshop_package(package_id);now=time.monotonic();cached=_CACHE.get(package_id)
 if cached and not force_refresh and now-cached[0]<ttl:return cached[1]
 data=urllib.parse.urlencode({'itemcount':'1','publishedfileids[0]':item_id}).encode('ascii')
 request=urllib.request.Request('https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/',data=data,headers={'User-Agent':'Capivara-Agent/1','Content-Type':'application/x-www-form-urlencoded'})
 with opener(request,timeout=30) as response:payload=json.loads(response.read().decode('utf-8'))
 details=((payload.get('response') or {}).get('publishedfiledetails') or [])
 revision=str((details[0] if details else {}).get('time_updated') or '').strip()
 if not revision.isdigit():raise RuntimeError('Steam Workshop revision metadata unavailable')
 _CACHE[package_id]=(now,revision);return revision

def detect_content_update(state:dict[str,Any],state_root:Path,*,opener=urllib.request.urlopen,force_refresh:bool=False)->dict[str,Any]:
 provider=str(state.get('provider') or '').strip().lower();ctype=str(state.get('content_type') or '').strip().lower();package=str(state.get('package_id') or '').strip()
 base={'schema_version':1,'provider':provider,'content_type':ctype,'package_id':package or None,'rollback_supported':True}
 if provider!='steam' or ctype!='workshop' or not package:return {**base,'detector_supported':False,'state':'unsupported','installed_revision':None,'available_revision':None}
 installed=installed_workshop_revision(state_root,package);available=upstream_workshop_revision(package,opener=opener,force_refresh=force_refresh)
 status='unknown' if not installed else 'up_to_date' if installed==available else 'update_available'
 return {**base,'detector_supported':True,'state':status,'installed_revision':installed,'available_revision':available}

__all__=['detect_content_update','installed_workshop_revision','parse_workshop_manifest','parse_workshop_package','upstream_workshop_revision']
