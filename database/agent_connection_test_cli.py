#!/usr/bin/env python3
"""Non-destructive OpenSSH preflight for prospective Agents."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for candidate in (ROOT,ROOT/"core"):
    if str(candidate) not in sys.path:sys.path.insert(0,str(candidate))
from agent_ssh_deploy import AgentDeployError,SSHDeployOptions,preflight_ssh,preflight_windows_ssh

def build_parser():
    p=argparse.ArgumentParser(description="Test SSH access to a Linux or Windows host without installing an Agent",epilog="Use --password-file for newly installed hosts. The password itself is never accepted on the command line.")
    p.add_argument("host");p.add_argument("--platform",choices=("linux","windows"),default="linux");p.add_argument("--ssh-user",required=True);p.add_argument("--ssh-port",type=int,default=22);auth=p.add_mutually_exclusive_group();auth.add_argument("--identity-file");auth.add_argument("--password-file");p.add_argument("--connect-timeout",type=int,default=10);p.add_argument("--json",action="store_true");return p

def main(argv=None):
    p=build_parser();a=p.parse_args(argv);options=SSHDeployOptions(a.host,a.ssh_user,a.ssh_port,a.identity_file,a.password_file,a.connect_timeout)
    try:r=(preflight_windows_ssh if a.platform=="windows" else preflight_ssh)(options)
    except AgentDeployError as exc:
        if a.json:print(json.dumps({"ok":False,"error":str(exc)},ensure_ascii=False));return 2
        p.exit(2,f"Erro: {exc}\n")
    out={"ok":True,"host":a.host,"ssh_port":a.ssh_port,"platform":r.get("platform"),"architecture":r.get("architecture"),"transport":"openssh","authentication":"password-file" if a.password_file else "ssh-key-or-agent"}
    if a.json:print(json.dumps(out,ensure_ascii=False,sort_keys=True))
    else:
        print("Capivara Agent Connection Test\n");print(f"Host.............. {a.host}:{a.ssh_port}");print("SSH............... OK");print(f"Platform.......... {out['platform']}");print(f"Architecture...... {out['architecture']}");print(f"Authentication.... {out['authentication']}");print("Ready............. YES")
    return 0
if __name__=="__main__":raise SystemExit(main())
