#!/usr/bin/env python3
"""Filesystem-safe DayZ mission discovery, switching and wipe helpers."""
from __future__ import annotations
from datetime import datetime,timezone
import re,shutil,tarfile,uuid
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
    path=_config(record)
    try:source=path.read_text(encoding="utf-8",errors="replace")
    except OSError:source=""
    match=_TEMPLATE.search(source)
    if match:return _safe(match.group(2).strip())
    value=str(record.get("mission") or "").strip()
    if value and _SAFE.fullmatch(value):return value
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
def mod_compatibility_preflight(snapshot,mission):
    mission=_safe(mission)
    entries=(snapshot or {}).get("entries") if isinstance(snapshot,dict) else []
    if not isinstance(entries,list):entries=[]
    dayz=[]
    for raw in entries:
        if not isinstance(raw,dict):continue
        activation=raw.get("activation") if isinstance(raw.get("activation"),dict) else {}
        if str(raw.get("game_id") or "").strip().lower()!="dayz" and str(activation.get("adapter") or "").strip().lower()!="dayz":continue
        dayz.append(dict(raw))
    active_ids={str(item.get("content_id") or "").strip() for item in dayz if str(item.get("content_id") or "").strip()}
    items=[];compatible=unknown=incompatible=0
    for item in dayz:
        cid=str(item.get("content_id") or item.get("package_id") or "conteúdo").strip()
        package=str(item.get("package_id") or "").strip() or None
        missing=[str(dep).strip() for dep in item.get("dependencies") or [] if str(dep).strip() not in active_ids]
        rules=item.get("dayz_map_compatibility") if isinstance(item.get("dayz_map_compatibility"),dict) else {}
        allowed=[str(value).strip() for value in rules.get("compatible_missions") or [] if _SAFE.fullmatch(str(value).strip())]
        denied=[str(value).strip() for value in rules.get("incompatible_missions") or [] if _SAFE.fullmatch(str(value).strip())]
        reason=None
        if missing:
            state="incompatible";reason="missing_dependency"
        elif mission in denied:
            state="incompatible";reason="explicit_incompatibility"
        elif allowed:
            state="compatible" if mission in allowed else "incompatible"
            if state=="incompatible":reason="mission_not_in_compatibility_allowlist"
        elif rules.get("all_missions") is True:
            state="compatible"
        else:
            state="unknown";reason="compatibility_not_declared"
        if state=="compatible":compatible+=1
        elif state=="unknown":unknown+=1
        else:incompatible+=1
        items.append({"content_id":cid,"package_id":package,"status":state,"reason":reason,"missing_dependencies":missing})
    status="incompatible" if incompatible else ("unknown" if unknown else "compatible")
    return {
        "mission":mission,
        "status":status,
        "blocking":bool(incompatible),
        "active_mods":len(dayz),
        "compatible":compatible,
        "unknown":unknown,
        "incompatible":incompatible,
        "items":items,
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
        def replace_mission_bind(raw):
            binds=[]
            for item in raw or []:
                if not isinstance(item,dict):continue
                source=str(item.get("source") or "");target=str(item.get("target") or "")
                mission_bind=False
                try:mission_bind=Path(source).parent.resolve()==(state_root/"mpmissions").resolve() or Path(target).parent.resolve()==(working/"mpmissions").resolve()
                except Exception:mission_bind=False
                if not mission_bind:binds.append(dict(item))
            binds.append({"source":str(private),"target":str(shared)})
            return binds
        result["bind_paths"]=replace_mission_bind(record.get("bind_paths"))
        if isinstance(record.get("content_base_bind_paths"),list):
            result["content_base_bind_paths"]=replace_mission_bind(record.get("content_base_bind_paths"))
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
def prepare_mission_persistence(record,mission,mode="keep"):
    mission=_safe(mission);mode=str(mode or "keep").strip().lower()
    if mode not in {"keep","fresh"}:raise ValueError("invalid DayZ map persistence mode")
    paths=_persistence_paths(record,mission);existing=[str(path) for path in paths if path.exists()]
    result={"mode":mode,"mission":mission,"existing":existing,"archived":[],"backup_root":None}
    if mode=="keep" or not existing:return result
    root=_root(record);stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ");token=uuid.uuid4().hex[:8]
    backup_root=root/"backups"/"dayz-map-switch"/mission/f"{stamp}-{token}";backup_root.mkdir(parents=True,exist_ok=False)
    archived=[]
    for path in paths:
        if not path.exists():continue
        resolved=path.resolve()
        try:relative=resolved.relative_to(root)
        except ValueError:raise ValueError(f"DayZ persistence path escapes instance root: {resolved}")
        target=backup_root/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.move(str(resolved),str(target))
        archived.append({"original":str(resolved),"backup":str(target)})
    result["archived"]=archived;result["backup_root"]=str(backup_root)
    return result

def restore_mission_persistence(preparation):
    if not isinstance(preparation,dict):return {"restored":[]}
    archived=preparation.get("archived") if isinstance(preparation.get("archived"),list) else []
    restored=[]
    for item in reversed(archived):
        if not isinstance(item,dict):continue
        original=Path(str(item.get("original") or "")).resolve();backup=Path(str(item.get("backup") or "")).resolve()
        if not backup.exists():continue
        if original.is_dir():shutil.rmtree(original)
        elif original.exists():original.unlink()
        original.parent.mkdir(parents=True,exist_ok=True);shutil.move(str(backup),str(original));restored.append(str(original))
    backup_root=str(preparation.get("backup_root") or "").strip()
    if backup_root:
        root=Path(backup_root)
        try:shutil.rmtree(root)
        except OSError:pass
    return {"restored":restored}

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
__all__=["apply_mission","current_mission","discover_missions","mod_compatibility_preflight","prepare_mission_persistence","restore_mission_persistence","wipe"]
