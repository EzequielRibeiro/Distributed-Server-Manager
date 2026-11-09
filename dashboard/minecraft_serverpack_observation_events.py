"""Persist Hybrid Agent physical observations as audit evidence, not health.

The event log is an existing append-only source; there is no new mutable
health table, and a stored observation alone cannot authorize a release.
"""
from __future__ import annotations

from datetime import datetime, timezone
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


def persist_serverpack_runtime_observations(
        backend:Any,*,agent_id:str,observations:list[dict[str,Any]],
        observed_at:str)->dict[str,int]:
    """Only local owned Agent observations; never promote an event to healthy."""
    stamp=_timestamp(observed_at)
    if not agent_id or not stamp:
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
        key=(agent_id,iid,cid,str(revision),status,reason,stamp)
        event_id='minecraft-serverpack-observed-'+hashlib.sha256('\0'.join(key).encode()).hexdigest()
        if event_id in seen:continue
        seen.add(event_id)
        saved=events.publish({
            'event_id':event_id,'event_type':'MINECRAFT_SERVERPACK_RUNTIME_OBSERVED',
            'occurred_at':stamp,'source':'controller.local_hybrid_serverpack_observer',
            'source_id':agent_id,'agent_id':agent_id,'instance_id':iid,
            'severity':'info' if status=='physical_runtime_verified' else 'warning',
            'data':{'content_id':cid,'bundle_revision':revision,
                    'observation_status':status,'reason':reason,
                    'proof_scope':'current_filesystem_only',
                    'boot_verified':False,'release_authorized':False},
        })
        created+=int(saved['created'])
    return {'accepted':len(seen),'created':created}


def classify_recent_serverpack_observation(
        item:dict[str,Any]|None,*,agent_id:str,instance_id:str,
        content_id:str,bundle_revision:int,now:datetime|None=None,
        max_age_seconds:int=7200)->str:
    """Fail-closed freshness projection; never returns healthy/ready."""
    if not isinstance(item,dict) or max_age_seconds<=0:return 'missing'
    data=item.get('data')
    if not isinstance(data,dict):return 'missing'
    if (item.get('event_type')!='MINECRAFT_SERVERPACK_RUNTIME_OBSERVED'
        or item.get('agent_id')!=agent_id or item.get('instance_id')!=instance_id
        or data.get('content_id')!=content_id
        or type(data.get('bundle_revision')) is not int
        or data['bundle_revision']!=bundle_revision
        or data.get('proof_scope')!='current_filesystem_only'
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