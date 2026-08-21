#!/usr/bin/env python3
"""Controller CLI for D2 API credentials and real-time status."""
from __future__ import annotations
import argparse,json
from api_access_repository import ApiAccessRepository
from realtime_repository import RealtimeRepository
from runtime_backend import backend_from_environment

def main(argv=None):
 p=argparse.ArgumentParser(prog="cap api");sub=p.add_subparsers(dest="command",required=True)
 ls=sub.add_parser("token-list");ls.add_argument("--json",action="store_true")
 cr=sub.add_parser("token-create");cr.add_argument("name");cr.add_argument("--scope",action="append",dest="scopes");cr.add_argument("--expires-at");cr.add_argument("--json",action="store_true")
 rv=sub.add_parser("token-revoke");rv.add_argument("token_id");rv.add_argument("--json",action="store_true")
 st=sub.add_parser("status");st.add_argument("--json",action="store_true")
 args=p.parse_args(argv);backend=backend_from_environment();repo=ApiAccessRepository(backend);repo.initialize()
 if args.command=="token-list":out=repo.list_tokens()
 elif args.command=="token-create":out=repo.create_token(name=args.name,scopes=args.scopes,expires_at=args.expires_at,created_by="cli")
 elif args.command=="token-revoke":out=repo.revoke(args.token_id)
 else:
  realtime=RealtimeRepository(backend);realtime.initialize();out=realtime.status()
 if getattr(args,"json",False):print(json.dumps(out,indent=2,sort_keys=True))
 else:
  if isinstance(out,list):
   for row in out:print(json.dumps(row,sort_keys=True))
  else:print(json.dumps(out,sort_keys=True))
 return 0
if __name__=="__main__":raise SystemExit(main())
