#!/usr/bin/env python3
"""Read-only Agent-side runtime observation for a canonical Minecraft Server Pack.

This is an explicit local probe, not a heartbeat or a release authorization.
It never starts/restarts/stops a process, writes game files or changes a DB.
The calling Agent must supply the Controller-approved canonical bundle.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

ROOT=Path(__file__).resolve().parents[1]
for source in (ROOT/'core',ROOT/'agents/common'):
    if str(source) not in sys.path:sys.path.insert(0,str(source))
from minecraft_serverpack_physical_manifest import attest_serverpack_mods
from minecraft_serverpack_agent import verify_installed_neoforge


def observe_runtime(runtime:Path,*,instance_id:str,content_id:str,
                    bundle:Mapping[str,Any])->dict[str,Any]:
    """Verify an existing runtime's exact NeoForge build and every managed JAR."""
    base={'kind':'MinecraftServerPackRuntimeObservation',
          'instance_id':instance_id,'content_id':content_id,
          'status':'unverified','ready_for_release':False,'boot_verified':False}
    if not isinstance(bundle,Mapping) or str(bundle.get('loader_id') or '')!='neoforge':
        return {**base,'reason':'invalid_loader_contract'}
    version=str(bundle.get('loader_version') or '')
    try:
        loader=verify_installed_neoforge(Path(runtime),version)
    except (OSError,ValueError,TypeError) as exc:
        return {**base,'reason':'loader_mismatch','detail':type(exc).__name__}
    try:
        proof=attest_serverpack_mods(Path(runtime),instance_id=instance_id,
                                      content_id=content_id,bundle=bundle)
    except (OSError,ValueError,TypeError) as exc:
        return {**base,'reason':'physical_manifest_mismatch',
                'detail':type(exc).__name__}
    return {**base,'status':'physical_runtime_verified',
            'reason':'boot_not_observed',
            'loader_version':loader['loader_version'],
            'manifest_sha256':proof['manifest_sha256'],
            'mod_count':proof['mod_count']}


def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',required=True,type=Path)
    parser.add_argument('--manifest',required=True,type=Path)
    parser.add_argument('--instance-id',required=True)
    parser.add_argument('--content-id',required=True)
    args=parser.parse_args()
    try:
        if args.manifest.is_symlink() or args.manifest.stat().st_size>16*1024*1024:
            raise ValueError('unsafe manifest file')
        bundle=json.loads(args.manifest.read_text(encoding='utf-8'))
        result=observe_runtime(args.runtime,instance_id=args.instance_id,
                               content_id=args.content_id,bundle=bundle)
    except (OSError,ValueError,TypeError) as exc:
        result={'kind':'MinecraftServerPackRuntimeObservation','status':'unverified',
                'ready_for_release':False,'boot_verified':False,
                'reason':'invalid_manifest_input','detail':type(exc).__name__}
    print(json.dumps(result,sort_keys=True))
    return 0 if result['status']=='physical_runtime_verified' else 1


if __name__=='__main__':raise SystemExit(main())