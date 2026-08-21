#!/usr/bin/env python3
"""Controller CLI for Universal Smart Backup."""
from __future__ import annotations
import argparse,json
from backup_repository import BackupRepository
from runtime_backend import backend_from_environment
def repo():
 r=BackupRepository(backend_from_environment());r.initialize();return r
def main(argv=None):
 p=argparse.ArgumentParser(prog="cap backup-store");sub=p.add_subparsers(dest="command",required=True)
 pol=sub.add_parser("policy-set");pol.add_argument("--instance",required=True);pol.add_argument("--enabled",choices=("true","false"),default="true");pol.add_argument("--mode",choices=("full","config","world","custom"),default="full");pol.add_argument("--consistency",choices=("live","quiesced","stopped"),default="live");pol.add_argument("--compression",choices=("gzip","none"),default="gzip");pol.add_argument("--interval",type=int,default=21600);pol.add_argument("--retention",type=int,default=7);pol.add_argument("--include-json",default="[]");pol.add_argument("--exclude-json",default="[]");pol.add_argument("--json",action="store_true")
 pls=sub.add_parser("policy-list");pls.add_argument("--agent");pls.add_argument("--json",action="store_true")
 hist=sub.add_parser("history");hist.add_argument("policy_id");hist.add_argument("--json",action="store_true")
 jobs=sub.add_parser("jobs");jobs.add_argument("--instance");jobs.add_argument("--agent");jobs.add_argument("--status");jobs.add_argument("--json",action="store_true")
 for name in ("create","restore","delete"):
  sp=sub.add_parser(name);sp.add_argument("--instance",required=True);sp.add_argument("--backup");sp.add_argument("--json",action="store_true")
 args=p.parse_args(argv);r=repo()
 if args.command=="policy-list":out=r.list_policies(agent_id=args.agent)
 elif args.command=="history":out=r.history(args.policy_id)
 elif args.command=="jobs":out=r.list_jobs(instance_id=args.instance,agent_id=args.agent,status=args.status)
 elif args.command=="policy-set":
  try:inc=json.loads(args.include_json);exc=json.loads(args.exclude_json)
  except json.JSONDecodeError as e:p.error(str(e))
  out=r.put_policy({"instance_id":args.instance,"enabled":args.enabled=="true","mode":args.mode,"consistency":args.consistency,"compression":args.compression,"interval_seconds":args.interval,"retention_count":args.retention,"include_paths":inc,"exclude_paths":exc},requested_by="cli")
 else:
  if args.command in {"restore","delete"} and not args.backup:p.error("--backup is required")
  out=r.request(args.instance,action=args.command,backup_id=args.backup,reason="manual",requested_by="cli")
 if getattr(args,"json",False):print(json.dumps(out,indent=2,sort_keys=True,default=str))
 else:
  rows=out if isinstance(out,list) else [out.get("policy",out)]
  for row in rows:print(f"{row.get('instance_id',''):<28} {row.get('action',row.get('mode','')):<10} {row.get('status','')} {row.get('backup_id','') or ''}")
 return 0
if __name__=="__main__":raise SystemExit(main())
