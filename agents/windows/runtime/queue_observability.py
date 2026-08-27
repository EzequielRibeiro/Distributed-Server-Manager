"""Safe operational queue telemetry for the Windows Agent."""
from __future__ import annotations
import json,time
from pathlib import Path
from typing import Any
QUEUE_PATTERNS={"instance_results":"instance-results/*.json","console_results":"console-results/*.json","file_results":"file-results/*.json","resource_results":"resource-results/*.json","artifact_results":"artifact-results/*.json","provisioning":"instance-provisioning/*.request.json","storage_pool_migrations":"storage-pool-migrations/*.request.json","game_data":"game-data-jobs/*.json","backup_results":"backup-results/*.json","broadcast_state":"broadcast-state/*.json","runtime_events":"runtime-events/*.json"}
_ALLOWED_STATUS={"pending","queued","retrying","running","completed","failed","acknowledged","unknown"}
def _safe_json(path:Path)->dict[str,Any]:
 try:value=json.loads(path.read_text(encoding="utf-8"))
 except (OSError,ValueError):return {}
 return value if isinstance(value,dict) else {}
def _retry_count(payload:dict[str,Any])->int:
 for key in ("retry_count","retries","attempt_count","attempts"):
  value=payload.get(key)
  if isinstance(value,int) and not isinstance(value,bool):return max(0,value)
 return 0
def collect_queue_observability(state_dir:Path,*,now:float|None=None,stale_after_seconds:int=300)->dict[str,dict[str,Any]]:
 current=time.time() if now is None else float(now);threshold=max(1,int(stale_after_seconds));result={}
 for name,pattern in QUEUE_PATTERNS.items():
  files=sorted(state_dir.glob(pattern));oldest=0;max_retry=0;statuses={};unreadable=0
  for path in files:
   try:oldest=max(oldest,max(0,int(current-path.stat().st_mtime)))
   except OSError:pass
   payload=_safe_json(path)
   if not payload:unreadable+=1;continue
   max_retry=max(max_retry,_retry_count(payload));status=str(payload.get("status") or "").strip().lower()
   if status in _ALLOWED_STATUS:statuses[status]=statuses.get(status,0)+1
  result[name]={"depth":len(files),"oldest_age_seconds":oldest if files else 0,"stale":bool(files and oldest>=threshold),"stale_after_seconds":threshold,"max_retry_count":max_retry,"unreadable_items":unreadable,"statuses":statuses}
 return result
__all__=["QUEUE_PATTERNS","collect_queue_observability"]
