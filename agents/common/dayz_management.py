#!/usr/bin/env python3
"""Filesystem-safe DayZ mission discovery, switching and wipe helpers."""
from __future__ import annotations
from datetime import datetime,timezone
import re,shutil,tarfile
from pathlib import Path
from typing import Any
_SAFE=re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_TEMPLATE=re.compile(r'(\btemplate\s*=\s*["\'])([^"\']+)(["\']\s*;)',re.I)
_OFFICIAL={"dayzOffline.chernarusplus":"Chernarus","dayzOffline.enoch":"Livonia","dayzOffline.sakhal":"Sakhal"}

def _root(record):
    value=str(record.get("instance_state_root") or "").strip()
    if not value:raise ValueError("DayZ instance_state_root is unavailable")
    return Path(value).resolve()
def _working(record):
    value=str(record.get("working_directory") or "").strip()
    if not value:raise ValueError("DayZ working_directory is unavailable")
    return Path(value).resolve()
def _config(record):
    value=str(record.get("config_path") or "").strip()
    return Path(value).resolve() if value else (_root(record)/"config"/"serverDZ.cfg").resolve()
def _safe(name):
    value=str(name or "").strip()
    if not _SAFE.fullmatch(value):raise ValueError("invalid DayZ mission")
    return value
def current_mission(record):
    value=str(record.get("mission") or "").strip()
    if value and _SAFE.fullmatch(value):return value
    path=_config(record)
    try:source=path.read_text(encoding="utf-8",errors="replace")
    except OSError:source=""
    match=_TEMPLATE.search(source)
    if match:return _safe(match.group(2).strip())
    for arg in record.get("arguments") or []:
        text=str(arg)
        if text.lower().startswith("-mission="):
            return _safe(Path(text.split("=",1)[1].strip().strip("\"'")).name)
    return "dayzOffline.chernarusplus"
def discover_missions(record):
    current=current_mission(record);root=_root(record);working=_working(record)
    private_root=root/"mpmissions";shared_root=working/"mpmissions"
    names=set(_OFFICIAL)
    locations={}
    for kind,base in (("instance",private_root),("runtime",shared_root)):
        try:items=list(base.iterdir())
        except OSError:items=[]
        for item in items:
            if item.is_dir() and _SAFE.fullmatch(item.name):
                names.add(item.name);locations.setdefault(item.name,set()).add(kind)
    if current:names.add(current)
    result=[]
    for name in sorted(names,key=lambda x:(_OFFICIAL.get(x,x).lower(),x.lower())):
        where=locations.get(name,set());official=name in _OFFICIAL
        installed="instance" in where
        available=installed or "runtime" in where
        active=name==current
        state="active" if active else ("installed" if installed else ("available" if available else "unavailable"))
        source="official-runtime" if official else ("community-instance" if installed else "community-runtime")
        result.append({
            "id":name,"name":_OFFICIAL.get(name,name),"official":official,"community":not official,
            "current":active,"active":active,"installed":installed,"available":available,
            "can_activate":available,"state":state,"source":source,
        })
    active_item=next((item for item in result if item["active"]),None)
    return {
        "schema_version":2,
        "current":current,
        "current_name":(active_item or {}).get("name",current),
        "missions":result,
        "counts":{
            "available":sum(1 for item in result if item["available"]),
            "installed":sum(1 for item in result if item["installed"]),
        },
    }
def _copy_if_needed(record,mission):
    state=_root(record)/"mpmissions"/mission
    if state.is_dir():return state
    source=_working(record)/"mpmissions"/mission
    if not source.is_dir():raise FileNotFoundError(f"DayZ mission is not installed: {mission}")
    state.parent.mkdir(parents=True,exist_ok=True);shutil.copytree(source,state)
    return state
def apply_mission(record,mission):
    mission=_safe(mission);view=discover_missions(record)
    available={x["id"] for x in view["missions"] if x.get("can_activate")}
    if mission not in available:raise FileNotFoundError(f"DayZ mission is not installed or available: {mission}")
    private=_copy_if_needed(record,mission);cfg=_config(record)
    source=cfg.read_text(encoding="utf-8",errors="replace")
    if not _TEMPLATE.search(source):raise ValueError("DayZ mission template not found in server config")
    updated=_TEMPLATE.sub(lambda m:m.group(1)+mission+m.group(3),source,count=1)
    temp=cfg.with_name("."+cfg.name+".mission.tmp");temp.write_text(updated,encoding="utf-8");temp.replace(cfg)
    args=[]
    for raw in record.get("arguments") or []:
        text=str(raw)
        if text.lower().startswith("-mission="):text=f"-mission={private}"
        args.append(text)
    result=dict(record);result["mission"]=mission;result["arguments"]=args
    profile_context=dict(record.get("profile_context") or {})
    profile_context["dayz_mission"]=mission
    profile_context["mission"]=mission
    result["profile_context"]=profile_context
    state_root=_root(record);working=_working(record);shared=working/"mpmissions"/mission
    seeds=[]
    for item in record.get("seed_directories") or []:
        if not isinstance(item,dict):continue
        target=str(item.get("target") or "")
        if target and Path(target).parent.resolve()==(state_root/"mpmissions").resolve():continue
        seeds.append(dict(item))
    seeds.append({"source":str(shared),"target":str(private)})
    result["seed_directories"]=seeds
    if str(record.get("adapter") or "").lower()=="systemd":
        binds=[]
        for item in record.get("bind_paths") or []:
            if not isinstance(item,dict):continue
            source=str(item.get("source") or "");target=str(item.get("target") or "")
            mission_bind=False
            try:mission_bind=Path(source).parent.resolve()==(state_root/"mpmissions").resolve() or Path(target).parent.resolve()==(working/"mpmissions").resolve()
            except Exception:mission_bind=False
            if not mission_bind:binds.append(dict(item))
        binds.append({"source":str(private),"target":str(shared)})
        result["bind_paths"]=binds
    return result
def _persistence_paths(record,mission):
    root=_root(record);private=_copy_if_needed(record,mission);paths=[]
    try:
        for item in private.iterdir():
            if item.is_dir() and item.name.lower().startswith("storage_"):paths.append(item)
    except OSError:pass
    for raw in record.get("arguments") or []:
        text=str(raw or "").strip()
        if not text.lower().startswith("-storage="):continue
        candidate=Path(text.split("=",1)[1].strip().strip("\"'"))
        if not candidate.is_absolute():candidate=root/candidate
        try:resolved=candidate.resolve();resolved.relative_to(root)
        except (OSError,ValueError):continue
        if resolved.exists() and resolved not in paths:paths.append(resolved)
    default_storage=(root/"storage").resolve()
    if default_storage.exists() and default_storage not in paths:paths.append(default_storage)
    return paths
def wipe(record,scope="persistence",backup=True):
    mission=current_mission(record);scope=str(scope or "persistence").strip().lower()
    if scope not in {"persistence","persistence-and-profiles"}:raise ValueError("invalid DayZ wipe scope")
    targets=_persistence_paths(record,mission)
    profiles=_root(record)/"profiles"
    if scope=="persistence-and-profiles" and profiles.exists():targets.append(profiles)
    archive=None
    if backup and targets:
        out=_root(record)/"backups"/"dayz-wipe";out.mkdir(parents=True,exist_ok=True)
        stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ");archive=out/f"{mission}-{stamp}.tar.gz"
        with tarfile.open(archive,"w:gz") as tar:
            for path in targets:tar.add(path,arcname=str(path.relative_to(_root(record))))
    removed=[]
    for path in targets:
        if path.is_dir():shutil.rmtree(path);removed.append(str(path))
        elif path.exists():path.unlink();removed.append(str(path))
    return {"mission":mission,"scope":scope,"backup":str(archive) if archive else None,"removed":removed}
__all__=["apply_mission","current_mission","discover_missions","wipe"]
