#!/usr/bin/env python3
"""Build a reproducible Windows Agent ZIP package from one Git commit."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
import subprocess,sys,zipfile
ROOT=Path(__file__).resolve().parents[1]
def git(*args:str)->bytes:return subprocess.check_output(["git","-C",str(ROOT),*args])
def git_text(*args:str)->str:return git(*args).decode("utf-8").strip()
def git_file(ref:str,path:str)->bytes:return git("show",f"{ref}:{path}")
def _tree_sources(ref:str,source_root:str,package_root:str,suffixes:tuple[str,...])->dict[str,str]:
 paths=git_text("ls-tree","-r","--name-only",ref,source_root).splitlines();out={}
 for source in paths:
  if source.endswith(suffixes):
   relative=source.removeprefix(source_root.rstrip("/")+"/");out[f"{package_root.rstrip('/')}/{relative}"]=source
 return out
def _runtime_sources(ref:str)->dict[str,str]:
 paths=git_text("ls-tree","-r","--name-only",ref,"agents/windows/runtime").splitlines();out={}
 for source in paths:
  if source.endswith(".py"):
   relative=source.removeprefix("agents/windows/");out[f"agent/{relative}"]=source
 return out
def main()->int:
 ref=sys.argv[1] if len(sys.argv)>1 else "HEAD";output_dir=Path(sys.argv[2]) if len(sys.argv)>2 else ROOT/"dist";commit=git_text("rev-parse",f"{ref}^{{commit}}");version=git_text("show",f"{ref}:version");channel="beta" if "-" in version else "stable";package_name=f"capivara-agent-windows-{version}";output_dir.mkdir(parents=True,exist_ok=True);archive=output_dir/f"{package_name}.zip";checksum=output_dir/f"{package_name}.zip.sha256";external_manifest=output_dir/f"{package_name}.manifest.json"
 sources={"install-agent.ps1":"agents/windows/installer/install-agent.ps1","agent/common/identity.py":"agents/common/identity.py","agent/updater/updater.py":"agents/windows/updater/updater.py",**_runtime_sources(ref),**_tree_sources(ref,"agents/windows/service","service",(".ps1",)),**_tree_sources(ref,"agents/windows/gui","gui",(".ps1",))}
 if subprocess.run(["git","-C",str(ROOT),"cat-file","-e",f"{ref}:agents/windows/installer/repair-agent.ps1"],capture_output=True).returncode==0:sources["repair-agent.ps1"]="agents/windows/installer/repair-agent.ps1"
 files={relative:git_file(ref,source) for relative,source in sorted(sources.items())};files["VERSION"]=(version+"\n").encode();files["config/README.md"]=b"Configuration is created during installation. Pairing secrets are never packaged.\n"
 manifest={"schema_version":1,"kind":"CapivaraAgentPackage","platform":"windows","version":version,"git_commit":commit,"channel":channel,"features":{"admin_gui":True,"tray_icon":True,"desktop_shortcut":True},"required_files":sorted(files),"files":{relative:{"sha256":hashlib.sha256(data).hexdigest(),"size":len(data)} for relative,data in sorted(files.items())}}
 manifest_bytes=(json.dumps(manifest,indent=2,sort_keys=True)+"\n").encode();files["manifest.json"]=manifest_bytes;archive.unlink(missing_ok=True);epoch=int(git_text("show","-s","--format=%ct",commit));import datetime;stamp=datetime.datetime.utcfromtimestamp(max(epoch,315532800));date_time=(stamp.year,stamp.month,stamp.day,stamp.hour,stamp.minute,stamp.second)
 with zipfile.ZipFile(archive,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as package:
  for relative,data in sorted(files.items()):
   info=zipfile.ZipInfo(f"{package_name}/{relative}",date_time=date_time);info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o644<<16;package.writestr(info,data)
 digest=hashlib.sha256(archive.read_bytes()).hexdigest();checksum.write_text(f"{digest}  {archive.name}\n",encoding="utf-8");external_manifest.write_bytes(manifest_bytes);print(f"Windows Agent package: {archive}");print(f"Checksum: {checksum}");print(f"Manifest: {external_manifest}");return 0
if __name__=="__main__":raise SystemExit(main())
