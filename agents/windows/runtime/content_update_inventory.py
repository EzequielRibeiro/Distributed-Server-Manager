"""Periodic, non-blocking managed-content update inventory for Windows Agent."""
from __future__ import annotations
import json,os,threading,time
from datetime import datetime,timezone
from pathlib import Path
from typing import Any,Callable
import content_client
from content_update_provider import detect_content_update
PROGRAM_DATA=Path(os.environ.get('PROGRAMDATA',r'C:\ProgramData'));STATE_ROOT=Path(os.environ.get('CAPIVARA_AGENT_STATE_DIR',PROGRAM_DATA/'CapivaraAgent'/'state'));INVENTORY_PATH=STATE_ROOT/'content-update-inventory.json';DEFAULT_INTERVAL_SECONDS=300;_LAST_REFRESH_MONOTONIC=0.0;_THREAD:threading.Thread|None=None;_THREAD_LOCK=threading.Lock()
def _now()->str:return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def _read()->dict[str,Any]:
 try:value=json.loads(INVENTORY_PATH.read_text(encoding='utf-8'))
 except (OSError,ValueError):return {'schema_version':1,'kind':'ContentUpdateInventory','checked_at':None,'content':[]}
 return value if isinstance(value,dict) else {'schema_version':1,'kind':'ContentUpdateInventory','checked_at':None,'content':[]}
def _write(payload:dict[str,Any])->None:
 INVENTORY_PATH.parent.mkdir(parents=True,exist_ok=True);temp=INVENTORY_PATH.with_suffix('.tmp');temp.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n',encoding='utf-8');os.replace(temp,INVENTORY_PATH)
def _interval(config:dict[str,Any])->int:
 try:value=int(config.get('content_update_check_interval_seconds',DEFAULT_INTERVAL_SECONDS))
 except (TypeError,ValueError):value=DEFAULT_INTERVAL_SECONDS
 return max(60,min(value,86400))
def refresh(config:dict[str,Any],*,force:bool=False)->dict[str,Any]:
 global _LAST_REFRESH_MONOTONIC
 now=time.monotonic()
 if not force and _LAST_REFRESH_MONOTONIC and now-_LAST_REFRESH_MONOTONIC<_interval(config):return _read()
 items=[]
 for state in content_client.content_state():
  if str(state.get('status') or '')!='applied' or not state.get('installed_version'):continue
  base={'instance_id':state.get('instance_id'),'content_id':state.get('content_id'),'checked_at':_now()}
  try:
   detail=detect_content_update(state,STATE_ROOT)
   if not detail.get('detector_supported'):continue
   items.append({**base,**detail})
  except Exception as exc:items.append({**base,'provider':state.get('provider'),'content_type':state.get('content_type'),'package_id':state.get('package_id'),'detector_supported':True,'state':'probe_failed','rollback_supported':True,'error':str(exc)[:2000]})
 payload={'schema_version':1,'kind':'ContentUpdateInventory','checked_at':_now(),'interval_seconds':_interval(config),'content':items};_write(payload);_LAST_REFRESH_MONOTONIC=now;return payload
def inventory()->dict[str,Any]:return _read()
def _background(config:dict[str,Any],logger:Callable[[str],Any]|None)->None:
 while True:
  try:refresh(config)
  except Exception as exc:
   if logger:
    try:logger(f'content update inventory failed: {exc}')
    except Exception:pass
  time.sleep(max(30,min(_interval(config),300)))
def start_background(config:dict[str,Any],logger:Callable[[str],Any]|None=None)->bool:
 global _THREAD
 with _THREAD_LOCK:
  if _THREAD is not None and _THREAD.is_alive():return False
  _THREAD=threading.Thread(target=_background,args=(dict(config),logger),name='capivara-content-update-inventory',daemon=True);_THREAD.start();return True
__all__=['DEFAULT_INTERVAL_SECONDS','inventory','refresh','start_background']
