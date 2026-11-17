"""Bounded Controller manifests for read-only remote Agent Server Pack probes."""
from __future__ import annotations
import json
from typing import Any

from content_repository import ContentRepository
from core.content_bundle import normalize_bundle


def requests_for_agent(backend:Any,*,agent_id:str,limit:int=1)->list[dict[str,Any]]:
    if not agent_id or not 1<=limit<=2:return []
    repo=ContentRepository(backend)
    out=[]
    for item in repo.list(agent_id=agent_id,limit=2000):
        if len(out)>=limit:break
        if item.get('content_type')!='modpack' or item.get('provider')!='local':continue
        artifact=item.get('artifact')
        if not isinstance(artifact,dict) or artifact.get('ephemeral_upload') is not True:continue
        iid=str(item.get('instance_id') or '')
        cid=str(item.get('content_id') or '')
        if not iid or not cid:continue
        current=repo._bundle_row(iid,cid)
        if not current or current.get('manifest_kind')!='serverpack-local-v1':continue
        try:
            history=repo._bundle_revision(iid,cid,int(current['revision']))
            payload=str(history.get('manifest_json') or '')
            if not payload or len(payload.encode('utf-8'))>512*1024:continue
            manifest=json.loads(payload)
            if (not isinstance(manifest,dict)
                or not isinstance(manifest.get('members'),list)
                or not 1<=len(manifest['members'])<=500):continue
            bundle={'provider':current['provider'],
                'provider_project_id':current['provider_project_id'],
                'provider_version_id':current['provider_version_id'],
                'minecraft_version':current['minecraft_version'],
                'loader_id':current['loader_id'],
                'loader_version':current['loader_version'],
                'manifest_kind':current['manifest_kind'],
                'override_roots':json.loads(history.get('override_roots_json') or '[]'),
                'members':manifest['members'],
                'manifest_sha256':current['manifest_sha256']}
            normalized=normalize_bundle({**bundle,'instance_id':iid,'parent_content_id':cid})
            if normalized['manifest_sha256']!=history.get('manifest_sha256'):continue
            out.append({'instance_id':iid,'content_id':cid,
                        'bundle_revision':int(current['revision']),
                        'manifest_sha256':normalized['manifest_sha256'],
                        'bundle':bundle})
        except (ValueError,TypeError,KeyError,AttributeError):
            continue
    return out


__all__=['requests_for_agent']