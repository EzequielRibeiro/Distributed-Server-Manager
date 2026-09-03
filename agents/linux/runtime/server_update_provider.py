#!/usr/bin/env python3
"""Typed, secret-free upstream version detection for game servers."""
from __future__ import annotations
import re, subprocess, time
from pathlib import Path
from typing import Any, Callable
_CACHE:dict[tuple[str,str],tuple[float,str]]={}
_TOKEN=re.compile(r'^[A-Za-z0-9._-]{1,64}$')
_BUILD=re.compile(r'"buildid"\s+"(\d+)"',re.I)

def _safe(value:Any,label:str)->str:
 text=str(value or '').strip()
 if not _TOKEN.fullmatch(text):raise ValueError(f'invalid {label}')
 return text

def parse_manifest_buildid(text:str)->str|None:
 m=_BUILD.search(str(text or ''));return m.group(1) if m else None

def parse_app_info_buildid(text:str,branch:str='public')->str|None:
 branch=_safe(branch,'Steam branch');lines=str(text or '').splitlines();needle='"'+branch+'"';inside=False;depth=0;seen=False
 for raw in lines:
  s=raw.strip()
  if not inside and s==needle:seen=True;continue
  if seen and not inside:
   if s=='{':inside=True;depth=1;seen=False
   elif s:seen=False
   continue
  if inside:
   depth+=s.count('{')-s.count('}')
   m=_BUILD.search(s)
   if m:return m.group(1)
   if depth<=0:return None
 return None

def _manifest_candidates(target:Path,appid:str)->list[Path]:
 name=f'appmanifest_{appid}.acf';home=Path.home();state=Path(__import__('os').environ.get('CAPIVARA_AGENT_STATE_DIR','/var/lib/capivara-agent'))
 return [target/'steamapps'/name,target.parent/'steamapps'/name,home/'.steam/steam/steamapps'/name,home/'.local/share/Steam/steamapps'/name,state/'tools/steamcmd/steamapps'/name]

def installed_steam_build(target:Path,appid:str)->str|None:
 appid=_safe(appid,'Steam AppID')
 if not appid.isdigit():raise ValueError('invalid Steam AppID')
 for p in _manifest_candidates(target,appid):
  try:v=parse_manifest_buildid(p.read_text(encoding='utf-8',errors='replace'))
  except OSError:continue
  if v:return v
 return None

def upstream_steam_build(appid:str,branch:str,steamcmd:str,*,ttl:int=300,runner:Callable[...,Any]=subprocess.run,force_refresh:bool=False)->str:
 appid=_safe(appid,'Steam AppID');branch=_safe(branch or 'public','Steam branch')
 if not appid.isdigit():raise ValueError('invalid Steam AppID')
 key=(appid,branch);now=time.monotonic();cached=_CACHE.get(key)
 if cached and not force_refresh and now-cached[0]<ttl:return cached[1]
 cp=runner([steamcmd,'+login','anonymous','+app_info_update','1','+app_info_print',appid,'+quit'],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=180,check=False)
 if cp.returncode!=0:raise RuntimeError('Steam update metadata lookup failed')
 build=parse_app_info_buildid(cp.stdout or '',branch)
 if not build:raise RuntimeError('Steam branch build metadata unavailable')
 _CACHE[key]=(now,build);return build

def detect_update(selection:dict[str,Any],target:Path,steamcmd:str|None=None,*,runner=subprocess.run,force_refresh:bool=False)->dict[str,Any]:
 provider=str(selection.get('provider') or '').strip().lower()
 if provider!='steam':return {'schema_version':1,'provider':provider,'detector_supported':False,'state':'unsupported','rollback_supported':False}
 install=selection.get('install') if isinstance(selection.get('install'),dict) else {};appid=str(install.get('package_id') or '').strip();branch=str(install.get('branch') or selection.get('branch') or 'public').strip()
 if steamcmd is None:
  from game_data_executor import _steamcmd
  steamcmd=_steamcmd()
 installed=installed_steam_build(target,appid);available=upstream_steam_build(appid,branch,steamcmd,runner=runner,force_refresh=force_refresh)
 state='unknown' if not installed else 'up_to_date' if installed==available else 'update_available'
 return {'schema_version':1,'provider':'steam','detector_supported':True,'app_id':appid,'branch':branch,'installed_version':installed,'available_version':available,'state':state,'rollback_supported':True}

__all__=['detect_update','installed_steam_build','parse_app_info_buildid','parse_manifest_buildid','upstream_steam_build']
