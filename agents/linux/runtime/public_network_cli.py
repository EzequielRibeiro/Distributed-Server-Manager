#!/usr/bin/env python3
"""Agent-local CLI for public game-server network identity."""
from __future__ import annotations
import argparse,json,os,sys,urllib.error,urllib.parse,urllib.request
from pathlib import Path
CONFIG_PATH=Path(os.environ.get("CAPIVARA_AGENT_CONFIG","/etc/capivara-agent/agent.json"))
def _config():
 value=json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
 if not isinstance(value,dict):raise RuntimeError("Agent config must be a JSON object")
 return value
def _request(method,payload=None):
 c=_config();base=str(c.get("controller_url") or "").rstrip("/")
 if not base:raise RuntimeError("controller_url is not configured")
 headers={"Accept":"application/json","X-Capivara-Agent-Credential":str(c.get("credential_id") or ""),"X-Capivara-Agent-Secret":str(c.get("credential_secret") or ""),"X-Capivara-Agent-Fingerprint":str(c.get("fingerprint") or "")}
 data=None
 if payload is not None:headers["Content-Type"]="application/json";data=json.dumps(payload).encode()
 req=urllib.request.Request(base+"/api/agent/public-network",data=data,headers=headers,method=method)
 try:
  with urllib.request.urlopen(req,timeout=10) as r:return json.loads(r.read().decode())
 except urllib.error.HTTPError as exc:raise RuntimeError(exc.read().decode(errors="replace") or str(exc)) from exc
 except urllib.error.URLError as exc:raise RuntimeError(f"Controller unavailable: {exc.reason}") from exc
def _emit(value):print(json.dumps(value,indent=2,ensure_ascii=False,default=str))
def main(argv=None):
 p=argparse.ArgumentParser(prog="cap agent network public");sub=p.add_subparsers(dest="action",required=True);sub.add_parser("show");sub.add_parser("test");s=sub.add_parser("set");s.add_argument("--hostname",default="");s.add_argument("--ipv4",default="")
 a=p.parse_args(argv)
 try:
  if a.action=="set":r=_request("POST",{"public_hostname":a.hostname,"public_ipv4":a.ipv4})
  else:r=_request("GET")
  _emit(r);return 0
 except Exception as exc:print(f"error: {exc}",file=sys.stderr);return 2
if __name__=="__main__":raise SystemExit(main())
