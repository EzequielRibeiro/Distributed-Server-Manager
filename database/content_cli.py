#!/usr/bin/env python3
"""Controller CLI for Universal Content desired state."""
from __future__ import annotations
import argparse,json
from content_repository import ContentRepository
from runtime_backend import backend_from_environment

def repo():
 r=ContentRepository(backend_from_environment());r.initialize();return r
def main(argv=None):
 p=argparse.ArgumentParser(prog="cap content-store");sub=p.add_subparsers(dest="command",required=True)
 ls=sub.add_parser("list");ls.add_argument("--agent");ls.add_argument("--instance");ls.add_argument("--state",choices=("installed","absent"));ls.add_argument("--limit",type=int,default=500);ls.add_argument("--json",action="store_true")
 setp=sub.add_parser("set");setp.add_argument("--agent");setp.add_argument("--instance",required=True);setp.add_argument("--content",required=True);setp.add_argument("--game");setp.add_argument("--type",default="other");setp.add_argument("--state",choices=("installed","absent"),default="installed");setp.add_argument("--version",default="latest");setp.add_argument("--provider",required=True);setp.add_argument("--target");setp.add_argument("--artifact-json",default="{}");setp.add_argument("--dependencies-json",default="[]");setp.add_argument("--conflicts-json",default="[]");setp.add_argument("--json",action="store_true")
 hist=sub.add_parser("history");hist.add_argument("assignment_id");hist.add_argument("--json",action="store_true")
 args=p.parse_args(argv);r=repo()
 if args.command=="list":out=r.list(agent_id=args.agent,instance_id=args.instance,desired_state=args.state,limit=args.limit)
 elif args.command=="history":out=r.history(args.assignment_id)
 else:
  try:artifact=json.loads(args.artifact_json);deps=json.loads(args.dependencies_json);conflicts=json.loads(args.conflicts_json)
  except json.JSONDecodeError as exc:p.error(str(exc))
  payload={"agent_id":args.agent,"instance_id":args.instance,"content_id":args.content,"game_id":args.game,"content_type":args.type,"desired_state":args.state,"version":args.version,"provider":args.provider,"target":args.target,"artifact":artifact,"dependencies":deps,"conflicts":conflicts};out=r.put(payload,requested_by="cli")
 if getattr(args,"json",False):print(json.dumps(out,indent=2,sort_keys=True))
 else:
  rows=out if isinstance(out,list) else [out.get("assignment",out)]
  for row in rows:print(f"{row.get('instance_id',''):<24} {row.get('content_id',''):<32} {row.get('desired_state','')} {row.get('version','')}")
 return 0
if __name__=="__main__":raise SystemExit(main())
