"""Bounded read-only Server Pack observation for the local Hybrid Agent.

Never installs, reconciles, restarts or persists health. Bundle authority comes
from the Controller DB, while the runtime path comes from the owned Agent record.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

from content_repository import ContentRepository
from scripts.minecraft_serverpack_observe_runtime import observe_runtime
_AGENT_RUNTIME=Path(__file__).resolve().parents[2]/"agents/linux/runtime"
if str(_AGENT_RUNTIME) not in sys.path:sys.path.insert(0,str(_AGENT_RUNTIME))
from minecraft_serverpack_boot_witness import observe_boot_witness
from minecraft_serverpack_live_readiness import (
    attest_live_serverpack_readiness, reserved_game_port)


def collect_hybrid_serverpack_observations(
    backend: Any, *, agent_id: str,
    read_instance: Callable[[str], dict[str, Any] | None], limit: int = 1,
) -> list[dict[str, Any]]:
    if not agent_id or not 1 <= limit <= 4:
        return []
    repo=ContentRepository(backend)
    observations=[]
    for parent in repo.list(agent_id=agent_id,limit=2000):
        if len(observations)>=limit:break
        if parent.get('content_type')!='modpack' or parent.get('provider')!='local':continue
        artifact=parent.get('artifact') or {}
        if not isinstance(artifact,dict) or not artifact.get('ephemeral_upload'):continue
        iid=str(parent.get('instance_id') or '')
        cid=str(parent.get('content_id') or '')
        if not iid or not cid:continue
        row=repo._bundle_row(iid,cid)
        if not row or row.get('manifest_kind')!='serverpack-local-v1':continue
        try:
            record=read_instance(iid)
            if (not isinstance(record,dict) or record.get('instance_id')!=iid
                    or record.get('agent_id')!=agent_id
                    or record.get('runtime_id')!='minecraft.java.neoforge'):
                continue
            source=record.get('working_directory')
            if not isinstance(source,str) or not Path(source).is_absolute():continue
            history=repo._bundle_revision(iid,cid,int(row['revision']))
            if history.get('manifest_sha256')!=row.get('manifest_sha256'):continue
            members=json.loads(history.get('manifest_json') or 'null')
            if not isinstance(members,dict) or not isinstance(members.get('members'),list):continue
            bundle={'provider':row['provider'],
                    'provider_project_id':row['provider_project_id'],
                    'provider_version_id':row['provider_version_id'],
                    'minecraft_version':row['minecraft_version'],
                    'loader_id':row['loader_id'],
                    'loader_version':row['loader_version'],
                    'manifest_kind':row['manifest_kind'],
                    'override_roots':json.loads(history.get('override_roots_json') or '[]'),
                    'members':members['members']}
            result=observe_runtime(Path(source),instance_id=iid,content_id=cid,bundle=bundle)
            if (result.get('status')=='physical_runtime_verified'
                    and result.get('manifest_sha256')!=row.get('manifest_sha256')):
                result={'status':'unverified','reason':'published_manifest_mismatch'}
            boot = (observe_boot_witness(Path(source), instance_id=iid)
                    if result.get('status')=='physical_runtime_verified' else None)
            game_port = reserved_game_port(record)
            operational = (attest_live_serverpack_readiness(
                Path(source), instance_id=iid, game_port=game_port,
                bundle_revision=int(row['revision']),
                manifest_sha256=row['manifest_sha256'])
                if result.get('status') == 'physical_runtime_verified' and game_port is not None
                else None)
            observations.append({'instance_id':iid,'content_id':cid,
                                 'bundle_revision':int(row['revision']),
                                 'manifest_sha256':row['manifest_sha256'],
                                 'status':result['status'],
                                 'reason':result['reason'],
                                 'boot_verified':False,
                                 'ready_for_release':False,
                                 **({'boot_observation':boot} if boot is not None else {}),
                                 **({'operational_attestation':operational} if operational is not None else {})})
        except (OSError,ValueError,TypeError,KeyError,AttributeError):
            game_port = reserved_game_port(record)
            operational = (attest_live_serverpack_readiness(
                Path(source), instance_id=iid, game_port=game_port,
                bundle_revision=int(row['revision']),
                manifest_sha256=row['manifest_sha256'])
                if result.get('status') == 'physical_runtime_verified' and game_port is not None
                else None)
            observations.append({'instance_id':iid,'content_id':cid,
                                 'bundle_revision':int(row['revision']),
                                 'status':'unverified','reason':'observation_error',
                                 'boot_verified':False,'ready_for_release':False})
    return observations


__all__=['collect_hybrid_serverpack_observations']