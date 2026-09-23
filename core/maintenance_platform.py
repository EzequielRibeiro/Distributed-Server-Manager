#!/usr/bin/env python3
"""Pure contracts for scheduled instance maintenance and restart planning."""
from __future__ import annotations
from datetime import date,datetime,time,timedelta,timezone
import re
from typing import Any,Mapping
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
SCHEDULE_MODES=frozenset({"fixed","interval"})
DEFAULT_WARNING_OFFSETS=(3600,1800,900,600,300,60)
DEFAULT_WARNING_TEMPLATE="Servidor será reiniciado em {remaining}."
_TIME=re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_PLACEHOLDER=re.compile(r"\{([^{}]+)\}")
_SAFE_TOKEN=re.compile(r"^[A-Za-z0-9._-]{1,191}$")
class MaintenanceValidationError(ValueError):pass
def _utc(value:datetime)->datetime:
 if value.tzinfo is None:raise MaintenanceValidationError("maintenance timestamps must be timezone-aware")
 return value.astimezone(timezone.utc)
def _parse_datetime(value:Any)->datetime|None:
 if value in {None,""}:return None
 if isinstance(value,datetime):return _utc(value)
 try:return _utc(datetime.fromisoformat(str(value).replace("Z","+00:00")))
 except (TypeError,ValueError) as exc:raise MaintenanceValidationError("invalid maintenance timestamp") from exc
def normalize_policy(raw:Mapping[str,Any]|None)->dict[str,Any]:
 value=dict(raw or {});enabled=bool(value.get("enabled",False));mode=str(value.get("schedule_mode") or "fixed").strip().lower()
 if mode not in SCHEDULE_MODES:raise MaintenanceValidationError("invalid maintenance schedule_mode")
 if mode=="fixed":
  zone_name=str(value.get("timezone") or "UTC").strip()
  try:ZoneInfo(zone_name)
  except (ZoneInfoNotFoundError,ValueError) as exc:raise MaintenanceValidationError("invalid maintenance timezone") from exc
  start_time=str(value.get("start_time") or "04:00").strip()
  if not _TIME.fullmatch(start_time):raise MaintenanceValidationError("invalid maintenance start_time")
  raw_days=value.get("weekdays",list(range(7)))
  if not isinstance(raw_days,list) or not raw_days:raise MaintenanceValidationError("maintenance weekdays must be a non-empty list")
  try:weekdays=sorted(set(int(day) for day in raw_days))
  except (TypeError,ValueError) as exc:raise MaintenanceValidationError("invalid maintenance weekdays") from exc
  if any(day<0 or day>6 for day in weekdays):raise MaintenanceValidationError("maintenance weekdays must be between 0 and 6")
 else:
  # Interval schedules are elapsed-time based. Wall-clock fields are
  # intentionally canonicalized so timezone/DST cannot affect the cadence.
  zone_name="UTC";start_time="04:00";weekdays=list(range(7))
 try:interval_seconds=int(value.get("interval_seconds") or 86400)
 except (TypeError,ValueError) as exc:raise MaintenanceValidationError("invalid maintenance interval_seconds") from exc
 if not 3600<=interval_seconds<=604800:raise MaintenanceValidationError("maintenance interval_seconds must be between 3600 and 604800")
 raw_offsets=value.get("warning_offsets_seconds",list(DEFAULT_WARNING_OFFSETS))
 if not isinstance(raw_offsets,list):raise MaintenanceValidationError("warning_offsets_seconds must be a list")
 try:offsets=sorted(set(int(offset) for offset in raw_offsets),reverse=True)
 except (TypeError,ValueError) as exc:raise MaintenanceValidationError("invalid warning_offsets_seconds") from exc
 if any(offset<=0 or offset>86400 for offset in offsets):raise MaintenanceValidationError("warning offsets must be between 1 and 86400 seconds")
 if mode=="interval" and offsets and max(offsets)>=interval_seconds:raise MaintenanceValidationError("warning offsets must be shorter than the maintenance interval")
 template=str(value.get("warning_template") or DEFAULT_WARNING_TEMPLATE).strip()
 if not template or len(template)>1024:raise MaintenanceValidationError("invalid maintenance warning_template")
 placeholders=set(_PLACEHOLDER.findall(template))
 if placeholders-{"remaining"}:raise MaintenanceValidationError("unsupported maintenance warning placeholder")
 stripped=_PLACEHOLDER.sub("",template)
 if "{" in stripped or "}" in stripped:raise MaintenanceValidationError("invalid maintenance warning_template braces")
 return {"enabled":enabled,"schedule_mode":mode,"timezone":zone_name,"weekdays":weekdays,"start_time":start_time,"interval_seconds":interval_seconds,"warning_offsets_seconds":offsets,"warning_template":template,"broadcast_enabled":bool(value.get("broadcast_enabled",True)),"coalesce_updates":bool(value.get("coalesce_updates",True))}
def _supported(value:Any)->bool:
 if isinstance(value,Mapping):return bool(value.get("supported",False))
 return bool(value)
def normalize_capabilities(raw:Mapping[str,Any]|None)->dict[str,bool]:
 value=dict(raw or {});save=value.get("save",value.get("graceful_save",False))
 return {"scheduled_restart":bool(value.get("scheduled_restart",True)),"broadcast":_supported(value.get("broadcast",False)),"save":_supported(save),"graceful_shutdown":_supported(value.get("graceful_shutdown",False)),"native_countdown":_supported(value.get("native_countdown",False))}
def _safe_optional_token(value:Any)->str|None:
 text=str(value or "").strip()
 return text if _SAFE_TOKEN.fullmatch(text) else None
def normalize_pending_work(raw_items:list[Mapping[str,Any]]|None)->list[dict[str,Any]]:
 pending=[];seen=set()
 statuses={"pending","dispatched","activated","aligned","committed","failed","skipped","rolling_back","rolled_back"}
 token_fields=("job_id","transaction_id","finalize_job_id","rollback_job_id")
 for raw in raw_items or []:
  if not isinstance(raw,Mapping):continue
  kind=str(raw.get("kind") or "").strip().lower();ref=str(raw.get("ref") or "").strip()[:191]
  if kind not in {"game-update","content-update","configuration"} or not ref:continue
  key=(kind,ref)
  if key in seen:continue
  seen.add(key);item={"kind":kind,"ref":ref}
  version=str(raw.get("available_version") or "").strip()[:191]
  if version:item["available_version"]=version
  try:revision=int(raw.get("desired_revision")) if raw.get("desired_revision") is not None else None
  except (TypeError,ValueError):revision=None
  if revision is not None and revision>0:item["desired_revision"]=revision
  status=str(raw.get("status") or "").strip().lower()
  if status in statuses:item["status"]=status
  error=str(raw.get("error") or "").replace("\x00","").strip()[:500]
  if error:item["error"]=error
  if kind=="game-update":
   for field in token_fields:
    token=_safe_optional_token(raw.get(field))
    if token:item[field]=token
  pending.append(item)
 return pending
def maintenance_event(policy:Mapping[str,Any],capabilities:Mapping[str,Any]|None,*,pending_work:list[Mapping[str,Any]]|None=None)->dict[str,Any]:
 p=normalize_policy(policy);caps=normalize_capabilities(capabilities)
 if not caps["scheduled_restart"]:raise MaintenanceValidationError("runtime does not support scheduled restart")
 pending=normalize_pending_work(pending_work);warnings=bool(p["broadcast_enabled"] and caps["broadcast"] and not caps["native_countdown"])
 steps=["warning"] if warnings else [];steps.append("preflight")
 if caps["save"]:steps.append("save")
 steps.append("stop")
 if p["coalesce_updates"] and pending:steps.append("apply-updates")
 steps.extend(["start","readiness"])
 return {"schema_version":1,"kind":"CapivaraMaintenanceEvent","capabilities":caps,"warnings_enabled":warnings,"coalesce_updates":p["coalesce_updates"],"pending_work":pending,"steps":steps}
def update_maintenance_event(event:Mapping[str,Any],*,pending_work:list[Mapping[str,Any]]|None=None,work_error:Any=None)->dict[str,Any]:
 value=dict(event or {})
 if value.get("kind")!="CapivaraMaintenanceEvent":raise MaintenanceValidationError("invalid maintenance event")
 if pending_work is not None:value["pending_work"]=normalize_pending_work(pending_work)
 if work_error is not None:
  error=str(work_error or "").replace("\x00","").strip()[:1000]
  value["work_error"]=error or None
 return value
def _valid_local_wall(zone:ZoneInfo,day:date,hh:int,mm:int)->datetime:
 naive=datetime.combine(day,time(hh,mm))
 for minute in range(181):
  candidate_naive=naive+timedelta(minutes=minute);candidate=candidate_naive.replace(tzinfo=zone,fold=0);roundtrip=candidate.astimezone(timezone.utc).astimezone(zone)
  if roundtrip.replace(tzinfo=None)==candidate_naive:return candidate
 raise MaintenanceValidationError("maintenance wall time cannot be resolved")
def next_due_at(policy:Mapping[str,Any],*,now:datetime|None=None,anchor:datetime|str|None=None)->datetime|None:
 normalized=normalize_policy(policy)
 if not normalized["enabled"]:return None
 current=_utc(now or datetime.now(timezone.utc))
 if normalized["schedule_mode"]=="interval":
  base=_parse_datetime(anchor) or current;interval=normalized["interval_seconds"];due=base+timedelta(seconds=interval)
  if due<=current:
   elapsed=(current-base).total_seconds();steps=int(elapsed//interval)+1;due=base+timedelta(seconds=steps*interval)
  return due
 zone=ZoneInfo(normalized["timezone"]);local_now=current.astimezone(zone);hh,mm=(int(part) for part in normalized["start_time"].split(":"))
 for delta_days in range(8):
  day=local_now.date()+timedelta(days=delta_days)
  if day.weekday() not in normalized["weekdays"]:continue
  candidate=_valid_local_wall(zone,day,hh,mm)
  if candidate>local_now:return candidate.astimezone(timezone.utc)
 raise MaintenanceValidationError("no maintenance occurrence found in the configured week")
def warning_plan(policy:Mapping[str,Any],due_at:datetime|str)->list[dict[str,Any]]:
 normalized=normalize_policy(policy);due=_parse_datetime(due_at)
 if due is None or not normalized["broadcast_enabled"]:return []
 return [{"offset_seconds":offset,"scheduled_at":due-timedelta(seconds=offset)} for offset in normalized["warning_offsets_seconds"]]
def due_warning_offsets(policy:Mapping[str,Any],due_at:datetime|str,*,now:datetime|None=None,sent_offsets:set[int]|None=None)->list[int]:
 current=_utc(now or datetime.now(timezone.utc));sent=set(sent_offsets or set());due=_parse_datetime(due_at)
 if due is None:return []
 return [int(item["offset_seconds"]) for item in warning_plan(policy,due) if int(item["offset_seconds"]) not in sent and current>=item["scheduled_at"] and current<due]
def format_remaining(seconds:int)->str:
 value=max(0,int(seconds))
 if value%3600==0:
  hours=value//3600;return f"{hours} hora" if hours==1 else f"{hours} horas"
 if value%60==0:
  minutes=value//60;return f"{minutes} minuto" if minutes==1 else f"{minutes} minutos"
 return f"{value} segundos"
def render_warning(policy:Mapping[str,Any],offset_seconds:int)->str:return normalize_policy(policy)["warning_template"].replace("{remaining}",format_remaining(offset_seconds))
__all__=["DEFAULT_WARNING_OFFSETS","DEFAULT_WARNING_TEMPLATE","MaintenanceValidationError","SCHEDULE_MODES","due_warning_offsets","format_remaining","maintenance_event","next_due_at","normalize_capabilities","normalize_pending_work","normalize_policy","render_warning","update_maintenance_event","warning_plan"]
