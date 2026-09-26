#!/usr/bin/env python3
"""Read-only offline structural inspection of a user-downloaded Server Pack.

Authenticated preview separately checks original CurseForge project/file SHA1.
No installation, extraction to disk or execution takes place.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"core"))
from minecraft_serverpack import inspect_serverpack,MinecraftServerPackError


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip",type=Path,help="ZIP downloaded from original publisher")
    parser.add_argument("--minecraft",default="26.1.2")
    parser.add_argument("--loader",default="neoforge")
    parser.add_argument("--loader-build",default="",help="exact publisher loader build")
    args=parser.parse_args()
    try:
        inspection=inspect_serverpack(args.zip,args.minecraft,args.loader,
           declared_loader_version=args.loader_build)
    except (MinecraftServerPackError,OSError,UnicodeDecodeError) as exc:
        print(f"SERVERPACK PREFLIGHT REJECTED: {exc}",file=sys.stderr)
        return 2
    inspection.pop("members",None)
    inspection["verified_by_curseforge"]=False
    inspection["requires_authenticated_official_hash_verification"]=True
    inspection["requires_agent_runtime_loader_verification"]=True
    print(json.dumps(inspection,indent=2,ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
