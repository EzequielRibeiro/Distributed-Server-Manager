"""Persist Hybrid Agent physical observations as audit evidence, not health.

The event log is an existing append-only source; there is no new mutable
health table, and a stored observation alone cannot authorize a release.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import hashlib
from typing import Any

from universal_event_repository import UniversalEventRepository


def _timestamp(value:Any)->str|None:
    if not isinstance(value,str) or len(value)>48:return None
    try:
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:return None
    parsed=parsed.astimezone(timezone.utc)
    now=datetime.now(timezone.utc)
    if abs((now-parsed).total_seconds())>300:return None
    return parsed.isoformat().replace('+00:00','Z')


def _advisory_boot(value:Any,stamp:str)->dict[str,Any]|None:
    """Bound an Agent-owned OS/log witness; never accept it as boot health."""
    if not isinstance(value,dict):return None
    if (value.get('status')!='boot_process_observed'
        or value.get('proof_scope')!='advisory_current_process_log'
        or value.get('reason')!='current_java_and_done_log_bound'
        or value.get('boot_verified') is not False
        or value.get('ready_for_release') is not False
        or type(value.get('java_pid')) is not int or value['java_pid']<=1):
        return None
    try:
        started=datetime.fromisoformat(value['java_started_at'].replace('Z','+00:00'))
        done=datetime.fromisoformat(value['done_at'].replace('Z','+00:00'))
        observed=datetime.fromisoformat(stamp.replace('Z','+00:00'))
        if not all(x.tzinfo is not None for x in (started,done,observed)):return None
        if not started <= done <= observed + timedelta(seconds=5):return None
        if (done-started).total_seconds()>1800:return None
    except (TypeError,ValueError,KeyError,OverflowError,AttributeError):return None
    return {'status':'boot_process_observed',
            'proof_scope':'advisory_current_process_log',
            'java_pid':value['java_pid'],
            'java_started_at':started.astimezone(timezone.utc).isoformat(),
            'done_at':done.astimezone(timezone.utc).isoformat(),
            'boot_verified':False,'ready_for_release':False}


def _functional_boot(value:Any,stamp:str,*,instance_id:str,
                     revision:int,manifest_sha256:str)->dict[str,Any]|None:
    """Validate an owned Agent's functional status proof; event remains non-authoritative."""
    if (not isinstance(value,dict)
        or value.get('status')!='functional_boot_attested'
        or value.get('proof_scope')!='owned_jvm_and_live_minecraft_status'
        or value.get('boot_verified') is not True
        or value.get('ready_for_release') is not False
        or value.get('instance_id')!=instance_id
        or type(value.get('bundle_revision')) is not int
        or value['bundle_revision']!=revision
        or value.get('manifest_sha256')!=manifest_sha256
        or type(value.get('game_port')) is not int
        or not 1 <= value['game_port'] <= 65535
        or type(value.get('java_pid')) is not int or value['java_pid']<=1):
        return None
    try:
        started=datetime.fromisoformat(value['java_started_at'].replace('Z','+00:00'))
        done=datetime.fromisoformat(value['done_at'].replace('Z','+00:00'))
        observed=datetime.fromisoformat(stamp.replace('Z','+00:00'))
        if not all(x.tzinfo is not None for x in (started,done,observed)):return None
        if not started <= done <= observed + timedelta(seconds=5):return None
        if (done-started).total_seconds()>1800:return None
    except (TypeError,ValueError,KeyError,OverflowError,AttributeError):return None
    return {'status':'functional_boot_attested',
            'proof_scope':'owned_jvm_and_live_minecraft_status',
            'instance_id':instance_id,'bundle_revision':revision,
            'manifest_sha256':manifest_sha256,'game_port':value['game_port'],
            'java_pid':value['java_pid'],
            'java_started_at':started.astimezone(timezone.utc).isoformat(),
            'done_at':done.astimezone(timezone.utc).isoformat(),
            'boot_verified':True,'ready_for_release':False}


def persist_serverpack_runtime_observations(
        backend:Any,*,agent_id:str,observations:list[dict[str,Any]],
        observed_at:str,source:str='controller.local_hybrid_serverpack_observer')->dict[str,int]:
    """Only local owned Agent observations; never promote an event to healthy."""
    stamp=_timestamp(observed_at)
    if (not agent_id or not stamp or source not in {
            'controller.local_hybrid_serverpack_observer',
            'controller.authenticated_agent_serverpack_observer'}):
        return {'accepted':0,'created':0}
    events=UniversalEventRepository(backend)
    seen=set()
    created=0
    for item in observations[:4]:
        if not isinstance(item,dict):continue
        iid=item.get('instance_id');cid=item.get('content_id')
        status=item.get('status');reason=item.get('reason')
        revision=item.get('bundle_revision')
        if (not isinstance(iid,str) or not iid or len(iid)>191
                or not isinstance(cid,str) or not cid or len(cid)>191
                or type(revision) is not int or revision<1
                or status not in {'physical_runtime_verified','unverified'}
                or not isinstance(reason,str) or not reason or len(reason)>100
                or item.get('boot_verified') is not False
                or item.get('ready_for_release') is not False):
            continue
        # A local probe may be stored only for an instance owned *now*.
        if not events._instance_owned_by(agent_id,iid):continue
        key=(source,agent_id,iid,cid,str(revision),status,reason,stamp)
        event_id='minecraft-serverpack-observed-'+hashlib.sha256('\0'.join(key).encode()).hexdigest()
        if event_id in seen:continue
        seen.add(event_id)
        digest=item.get('manifest_sha256')
        valid_digest=(isinstance(digest,str) and len(digest)==64
                      and all(ch in '0123456789abcdef' for ch in digest))
        advisory=(_advisory_boot(item.get('boot_observation'),stamp)
                  if status=='physical_runtime_verified' and valid_digest else None)
        functional=(_functional_boot(item.get('operational_attestation'),stamp,
                    instance_id=iid,revision=revision,manifest_sha256=digest)
                    if status=='physical_runtime_verified' and valid_digest else None)
        # A positive live status must belong to the very same JVM observed by
        # systemd and its boot log in this heartbeat. No cross-process mixing.
        if functional and (not advisory or any(
                functional.get(k)!=advisory.get(k)
                for k in ('java_pid','java_started_at','done_at'))):
            functional=None
        saved=events.publish({
            'event_id':event_id,'event_type':'MINECRAFT_SERVERPACK_RUNTIME_OBSERVED',
            'occurred_at':stamp,'source':source,
            'source_id':agent_id,'agent_id':agent_id,'instance_id':iid,
            'severity':'info' if status=='physical_runtime_verified' else 'warning',
            'data':{'content_id':cid,'bundle_revision':revision,
                    'observation_status':status,'reason':reason,
                    'proof_scope':'current_filesystem_only',
                    'boot_verified':False,'release_authorized':False,
                    **({'manifest_sha256':digest} if valid_digest else {}),
                    **({'boot_observation':advisory} if advisory else {}),
                    **({'operational_attestation':functional} if functional else {})},
        })
        created+=int(saved['created'])
    return {'accepted':len(seen),'created':created}


def classify_recent_serverpack_observation(
        item:dict[str,Any]|None,*,agent_id:str,instance_id:str,
        content_id:str,bundle_revision:int,now:datetime|None=None,
        max_age_seconds:int=7200,manifest_sha256:str|None=None)->str:
    """Fail-closed freshness projection; never returns healthy/ready."""
    if not isinstance(item,dict) or max_age_seconds<=0:return 'missing'
    data=item.get('data')
    if not isinstance(data,dict):return 'missing'
    if (item.get('event_type')!='MINECRAFT_SERVERPACK_RUNTIME_OBSERVED'
        or item.get('agent_id')!=agent_id or item.get('instance_id')!=instance_id
        or item.get('source') not in {'controller.local_hybrid_serverpack_observer',
                                      'controller.authenticated_agent_serverpack_observer'}
        or item.get('source_id')!=agent_id
        or data.get('content_id')!=content_id
        or type(data.get('bundle_revision')) is not int
        or data['bundle_revision']!=bundle_revision
        or data.get('proof_scope')!='current_filesystem_only'
        or (manifest_sha256 is not None and
            data.get('manifest_sha256')!=manifest_sha256)
        or data.get('boot_verified') is not False
        or data.get('release_authorized') is not False):
        return 'missing'
    stamp=item.get('occurred_at')
    if not isinstance(stamp,str):return 'missing'
    try:observed=datetime.fromisoformat(stamp.replace('Z','+00:00'))
    except ValueError:return 'missing'
    if observed.tzinfo is None:return 'missing'
    age=((now or datetime.now(timezone.utc))-observed).total_seconds()
    if age<0 or age>max_age_seconds:return 'stale'
    return ('verified' if data.get('observation_status')=='physical_runtime_verified'
            else 'unverified')

def record_authenticated_serverpack_observations(
        backend:Any,*,agent_id:str,payload:dict[str,Any]|None)->dict[str,int]:
    """Heartbeat-only transport: bind remote physical claims to current DB truth.

    The authenticated Agent identity is passed by the caller, not read from the
    JSON. A claim is advisory physical evidence, never process health or ready.
    """
    if not isinstance(payload,dict):return {'accepted':0,'created':0}
    timestamp=payload.get('observed_at')
    records=payload.get('observations')
    if not _timestamp(timestamp) or not isinstance(records,list):
        return {'accepted':0,'created':0}
    from content_repository import ContentRepository
    from alert_repository import AlertSession
    repository=ContentRepository(backend)
    bounded=[]
    for raw in records[:4]:
        if not isinstance(raw,dict):continue
        iid=raw.get('instance_id');cid=raw.get('content_id')
        revision=raw.get('bundle_revision');digest=raw.get('manifest_sha256')
        if (not isinstance(iid,str) or not iid or len(iid)>191
                or not isinstance(cid,str) or not cid or len(cid)>191
                or type(revision) is not int or revision<1
                or not isinstance(digest,str) or len(digest)!=64):continue
        # No user-provided Agent identity or manifest is authoritative.
        with backend.connect() as connection:
            session=AlertSession(backend,connection)
            try:
                current=session.execute(
                    f"SELECT agent_id,runtime_id FROM instances WHERE id={repository.ph}",
                    (iid,)).fetchone()
            finally:
                session.close()
        if (current is None or str(current['agent_id'] or '')!=agent_id
                or str(current['runtime_id'] or '')!='minecraft.java.neoforge'):
            continue
        row=repository._bundle_row(iid,cid)
        if (not row or row.get('manifest_kind')!='serverpack-local-v1'
                or int(row.get('revision') or 0)!=revision
                or row.get('manifest_sha256')!=digest):continue
        # Re-check immutable negative assertions in persist_serverpack_runtime_observations.
        bounded.append(raw)
    if not bounded:return {'accepted':0,'created':0}
    return persist_serverpack_runtime_observations(
        backend,agent_id=agent_id,observations=bounded,observed_at=timestamp,
        source='controller.authenticated_agent_serverpack_observer')