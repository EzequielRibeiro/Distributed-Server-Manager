"""Read-only authenticated-heartbeat response driven Server Pack observation.

The Agent does not obtain its expected hashes from a customer path or self
selected version. It uses a bounded manifest delivered by its Controller and
checks the instance identity from its own registry. Never modifies runtime.
"""
from __future__ import annotations

from datetime import datetime,timezone
from pathlib import Path
import sys
from typing import Any,Callable

_COMMON=Path(__file__).resolve().parents[2]/'common'
_CORE=Path(__file__).resolve().parents[3]/'core'
for _path in (_COMMON,_CORE):
    if str(_path) not in sys.path:sys.path.insert(0,str(_path))

from content_bundle import normalize_bundle
from minecraft_serverpack_agent import verify_installed_neoforge
from minecraft_serverpack_physical_manifest import attest_serverpack_mods
from minecraft_serverpack_boot_witness import observe_boot_witness
from minecraft_serverpack_live_readiness import (
    attest_live_serverpack_readiness, reserved_game_port)


def observe_remote_requests(requests:list[dict[str,Any]]|None,*,
                            agent_id:str,read_instance:Callable[[str],dict[str,Any]|None],
                            limit:int=1)->dict[str,Any]:
    stamp=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    output={'observed_at':stamp,'observations':[]}
    if not agent_id or not isinstance(requests,list) or not 1<=limit<=2:return output
    for request in requests[:limit]:
        if not isinstance(request,dict):continue
        iid=request.get('instance_id');cid=request.get('content_id')
        revision=request.get('bundle_revision');digest=request.get('manifest_sha256')
        bundle=request.get('bundle')
        if (not isinstance(iid,str) or not iid or len(iid)>191
            or not isinstance(cid,str) or not cid or len(cid)>191
            or type(revision) is not int or revision<1
            or not isinstance(digest,str) or len(digest)!=64
            or not isinstance(bundle,dict)):continue
        try:
            normalized=normalize_bundle({**bundle,'instance_id':iid,
                                          'parent_content_id':cid})
            if (normalized['manifest_sha256']!=digest
                or normalized['manifest_kind']!='serverpack-local-v1'
                or normalized['loader_id']!='neoforge'):
                continue
            record=read_instance(iid)
            if (not isinstance(record,dict) or record.get('instance_id')!=iid
                or record.get('agent_id')!=agent_id
                or record.get('runtime_id')!='minecraft.java.neoforge'):
                continue
            working=record.get('working_directory')
            if not isinstance(working,str) or not Path(working).is_absolute():continue
            path=Path(working)
            status='physical_runtime_verified';reason='boot_not_observed'
            try:
                verify_installed_neoforge(path,normalized['loader_version'])
                proof=attest_serverpack_mods(path,instance_id=iid,content_id=cid,bundle=bundle)
                if proof['manifest_sha256']!=digest:raise ValueError('manifest mismatch')
            except (OSError,ValueError,TypeError,KeyError):
                status='unverified';reason='physical_or_loader_mismatch'
            boot = (observe_boot_witness(path, instance_id=iid)
                    if status == 'physical_runtime_verified' else None)
            game_port = reserved_game_port(record)
            operational = (attest_live_serverpack_readiness(
                path, instance_id=iid, game_port=game_port,
                bundle_revision=revision, manifest_sha256=digest)
                if status == 'physical_runtime_verified' and game_port is not None
                else None)
            output['observations'].append({
                'instance_id':iid,'content_id':cid,'bundle_revision':revision,
                'manifest_sha256':digest,'status':status,'reason':reason,
                'boot_verified':False,'ready_for_release':False,
                **({'boot_observation':boot} if boot is not None else {}),
                **({'operational_attestation':operational} if operational is not None else {})})
        except (OSError,ValueError,TypeError,KeyError,AttributeError):
            continue
    return output


__all__=['observe_remote_requests']