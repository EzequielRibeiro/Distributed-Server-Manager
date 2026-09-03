#!/usr/bin/env python3
"""Canonical policy and state helpers for game-server updates."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MODES={"manual","automatic","maintenance"}
STATES={"unknown","checking","up_to_date","update_available","update_scheduled","updating","validating","updated","update_failed","rollback_required","unsupported"}
_TIME=re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")

class ServerUpdateValidationError(ValueError):pass

def normalize_policy(raw:dict[str,Any]|None)->dict[str,Any]:
 value=dict(raw or {});mode=str(value.get("mode") or "manual").strip().lower()
 if mode not in MODES:raise ServerUpdateValidationError("invalid update policy mode")
 tz=str(value.get("timezone") or "UTC").strip()
 try:ZoneInfo(tz)
 except (ZoneInfoNotFoundError,ValueError):raise ServerUpdateValidationError("invalid update policy timezone")
 start=str(value.get("start_time") or "04:00").strip()
 if not _TIME.fullmatch(start):raise ServerUpdateValidationError("invalid maintenance start_time")
 raw_days=value.get("weekdays",list(range(7)))
 if not isinstance(raw_days,list) or not raw_days:raise ServerUpdateValidationError("weekdays must be a non-empty list")
 try:days=sorted(set(int(x) for x in raw_days))
 except (TypeError,ValueError):raise ServerUpdateValidationError("invalid weekdays")
 if any(x<0 or x>6 for x in days):raise ServerUpdateValidationError("weekdays must be between 0 and 6")
 try:duration=int(value.get("duration_minutes",60));interval=int(value.get("check_interval_seconds",3600))
 except (TypeError,ValueError):raise ServerUpdateValidationError("invalid update policy interval")
 if not 15<=duration<=720:raise ServerUpdateValidationError("duration_minutes must be between 15 and 720")
 if not 900<=interval<=86400:raise ServerUpdateValidationError("check_interval_seconds must be between 900 and 86400")
 return {"mode":mode,"timezone":tz,"weekdays":days,"start_time":start,"duration_minutes":duration,"check_interval_seconds":interval,"backup_before_update":bool(value.get("backup_before_update",True))}

def maintenance_window_open(policy:dict[str,Any],now:datetime|None=None)->bool:
 p=normalize_policy(policy);local=(now or datetime.now(timezone.utc)).astimezone(ZoneInfo(p["timezone"]))
 if local.weekday() not in p["weekdays"]:return False
 hh,mm=map(int,p["start_time"].split(":"));start=local.replace(hour=hh,minute=mm,second=0,microsecond=0);end=start+timedelta(minutes=p["duration_minutes"])
 return start<=local<end

def classify_versions(installed:Any,available:Any)->str:
 a=str(installed or "").strip();b=str(available or "").strip()
 if not a or not b:return "unknown"
 return "up_to_date" if a==b else "update_available"

def should_apply(policy:dict[str,Any],state:str,*,now:datetime|None=None,manual:bool=False)->bool:
 if state!="update_available":return False
 p=normalize_policy(policy)
 if manual:return True
 if p["mode"]=="automatic":return True
 if p["mode"]=="maintenance":return maintenance_window_open(p,now)
 return False

__all__=["MODES","STATES","ServerUpdateValidationError","classify_versions","maintenance_window_open","normalize_policy","should_apply"]
