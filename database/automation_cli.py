#!/usr/bin/env python3
"""Controller CLI for D1 automation and universal broadcast."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# This CLI is executed directly as /opt/dsm/database/automation_cli.py. Python
# therefore places /opt/dsm/database on sys.path, while the automation stack
# mixes imports from the repository root (``core.*``) and legacy top-level
# modules stored inside ``core/`` (for example ``event_platform``). Make both
# locations explicit instead of depending on an ambient PYTHONPATH.
ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "core"):
 text = str(path)
 if text not in sys.path:
  sys.path.insert(0, text)

from automation_engine import AutomationEngine
from automation_repository import AutomationRepository
from runtime_backend import backend_from_environment


def main(argv=None):
 p=argparse.ArgumentParser(prog="cap automation");sub=p.add_subparsers(dest="command",required=True)
 rl=sub.add_parser("rule-list");rl.add_argument("--json",action="store_true")
 rs=sub.add_parser("rule-set");rs.add_argument("--json-body",required=True);rs.add_argument("--json",action="store_true")
 rh=sub.add_parser("history");rh.add_argument("rule_id");rh.add_argument("--json",action="store_true")
 fire=sub.add_parser("fire");fire.add_argument("rule_id");fire.add_argument("--context-json",default="{}");fire.add_argument("--json",action="store_true")
 ev=sub.add_parser("event");ev.add_argument("event_type");ev.add_argument("--event-id");ev.add_argument("--context-json",default="{}");ev.add_argument("--json",action="store_true")
 bs=sub.add_parser("broadcast");bs.add_argument("--scope",required=True);bs.add_argument("--target");bs.add_argument("--message",required=True);bs.add_argument("--priority",default="normal");bs.add_argument("--ttl",type=int,default=300);bs.add_argument("--no-ack",action="store_true");bs.add_argument("--json",action="store_true")
 bl=sub.add_parser("broadcast-list");bl.add_argument("--limit",type=int,default=200);bl.add_argument("--json",action="store_true")
 args=p.parse_args(argv);backend=backend_from_environment();repo=AutomationRepository(backend);repo.initialize();engine=AutomationEngine(backend)
 if args.command=="rule-list":out=repo.list_rules()
 elif args.command=="rule-set":out=repo.put_rule(json.loads(args.json_body),requested_by="cli")
 elif args.command=="history":out=repo.history(args.rule_id)
 elif args.command=="fire":out=engine.fire_rule(args.rule_id,context=json.loads(args.context_json),requested_by="cli")
 elif args.command=="event":
  context=json.loads(args.context_json);context["event_type"]=args.event_type;out=engine.fire("event",context,trigger_ref=args.event_id,requested_by="cli")
 elif args.command=="broadcast-list":out=repo.list_broadcasts(args.limit)
 else:out=repo.create_broadcast({"scope":args.scope,"target":args.target,"message":args.message,"priority":args.priority,"ttl_seconds":args.ttl,"require_ack":not args.no_ack},requested_by="cli")
 if getattr(args,"json",False):print(json.dumps(out,indent=2,sort_keys=True))
 else:
  if isinstance(out,list):
   for row in out:print(json.dumps(row,sort_keys=True))
  else:print(json.dumps(out,sort_keys=True))
 return 0
if __name__=="__main__":raise SystemExit(main())
