#!/usr/bin/env python3
"""Create protected password files for one-time remote Agent bootstrap."""
from __future__ import annotations
import argparse,getpass,os,re,sys,tempfile
from pathlib import Path
_NAME=re.compile(r"^[A-Za-z0-9._-]{1,80}$")
DEFAULT_DIR=Path(os.environ.get("DSM_REMOTE_DEPLOY_SECRET_DIR","/etc/capivara/secrets/remote-deploy"))

def build_parser():
    p=argparse.ArgumentParser(description="Manage protected remote-deploy secrets")
    sub=p.add_subparsers(dest="command",required=True)
    create=sub.add_parser("create",help="create or replace a protected SSH password file");create.add_argument("name",help="logical host/secret name");create.add_argument("--directory",default=str(DEFAULT_DIR),help=argparse.SUPPRESS)
    remove=sub.add_parser("delete",help="delete a remote-deploy secret");remove.add_argument("name");remove.add_argument("--directory",default=str(DEFAULT_DIR),help=argparse.SUPPRESS)
    return p

def _path(directory,name):
    if not _NAME.fullmatch(str(name or "")):raise ValueError("secret name may contain only letters, numbers, dot, underscore and hyphen")
    root=Path(directory).expanduser().resolve();return root,root/(name+".secret")

def create(directory,name):
    root,path=_path(directory,name);first=getpass.getpass("Senha SSH: ");second=getpass.getpass("Confirmar senha: ")
    if not first:raise ValueError("password cannot be empty")
    if first!=second:raise ValueError("password confirmation does not match")
    root.mkdir(parents=True,exist_ok=True);os.chmod(root,0o700)
    fd,tmp=tempfile.mkstemp(prefix=".capivara-secret-",dir=str(root),text=True)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,"w",encoding="utf-8") as handle:handle.write(first+"\n")
        os.replace(tmp,path);os.chmod(path,0o600)
    finally:
        try:os.unlink(tmp)
        except FileNotFoundError:pass
    return path

def delete(directory,name):
    _,path=_path(directory,name)
    try:path.unlink()
    except FileNotFoundError:raise ValueError(f"secret not found: {path}")
    return path

def main(argv=None):
    p=build_parser();a=p.parse_args(argv)
    try:
        if a.command=="create":path=create(a.directory,a.name);print("Remote deploy secret created");print(f"Path.............. {path}");print("Permissions....... 0600");print("Use............... cap agent deploy HOST --ssh-user USER --password-file "+str(path))
        else:path=delete(a.directory,a.name);print(f"Remote deploy secret deleted: {path}")
    except (ValueError,OSError) as exc:p.exit(2,f"Erro: {exc}\n")
    return 0
if __name__=="__main__":raise SystemExit(main())
