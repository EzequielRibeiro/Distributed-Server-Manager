"""Execute resolved game-data selections on a Windows Agent."""
from __future__ import annotations
import hashlib,json,os,shutil,subprocess,sys,tarfile,tempfile,time,urllib.request,zipfile
from pathlib import Path,PurePosixPath
from typing import Any
from game_data_files import execute_file_operation
from game_data_integrity import inspect_game_data
from game_data_installer import execute_installer
from game_data_state import GAME_DATA_ROOT,record_game_data,write_json
FILE_ACTIONS={"file-list","file-read","file-write","file-create","file-mkdir","file-rename","file-delete","file-upload"}
STEAMCMD_URL="https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"
def _safe(v,label):
 t=str(v or "").strip();allowed="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
 if not t or any(c not in allowed for c in t):raise ValueError(f"invalid {label}")
 return t
def _target(sel):
 game=_safe(sel.get("game"),"game");leaf=_safe(Path(str(sel.get("install_dir") or "serverfiles")).name or "serverfiles","install target");target=(GAME_DATA_ROOT/game/leaf).resolve();target.relative_to(GAME_DATA_ROOT);return target
def _managed_steamcmd():
 root=Path(os.environ.get("PROGRAMDATA") or r"C:\ProgramData")/"CapivaraAgent"/"tools"/"steamcmd"
 return root/"steamcmd.exe"
def _steamcmd():
 for c in (shutil.which("steamcmd.exe"),shutil.which("steamcmd"),os.environ.get("STEAMCMD_PATH"),str(_managed_steamcmd())):
  if c and Path(c).is_file():return str(c)
 raise RuntimeError("SteamCMD is not available on this Windows Agent")
def _probe_steamcmd(executable,attempts=3,retry_delay=3):
 last_returncode=None
 for attempt in range(attempts):
  cp=subprocess.run([str(executable),"+quit"],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=300,check=False,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
  print(cp.stdout or "",end="",flush=True)
  if cp.returncode==0:return
  last_returncode=cp.returncode
  if attempt+1<attempts:time.sleep(retry_delay)
 raise RuntimeError(f"SteamCMD validation failed with exit code {last_returncode} after {attempts} attempts")
def _install_steamcmd():
 try:
  existing=_steamcmd();_probe_steamcmd(existing)
  return {"provider":"system","component":"steamcmd","installed":True,"reused":True,"path":existing}
 except RuntimeError:
  pass
 target=_managed_steamcmd().parent;target.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.TemporaryDirectory(prefix="capivara-steamcmd-") as td:
  td_path=Path(td);archive=td_path/"steamcmd.zip";staging=td_path/"steamcmd"
  _download(STEAMCMD_URL,archive)
  if not zipfile.is_zipfile(archive):raise RuntimeError("SteamCMD download is not a valid ZIP archive")
  staging.mkdir();z=zipfile.ZipFile(archive)
  for i in z.infolist():_safe_member(i.filename)
  z.extractall(staging);z.close()
  executable=staging/"steamcmd.exe"
  if not executable.is_file():raise RuntimeError("SteamCMD archive does not contain steamcmd.exe")
  _probe_steamcmd(executable)
  if target.exists():shutil.rmtree(target)
  shutil.move(str(staging),str(target))
 installed=_managed_steamcmd()
 if not installed.is_file():raise RuntimeError("SteamCMD installation did not produce steamcmd.exe")
 return {"provider":"system","component":"steamcmd","installed":True,"reused":False,"path":str(installed)}
def _run_steam(sel,target):
 install=sel.get("install") if isinstance(sel.get("install"),dict) else {};app=str(install.get("package_id") or "").strip()
 if not app.isdigit():raise ValueError("Steam package_id is missing or invalid")
 auth=str(sel.get("auth") or "anonymous").lower();login="anonymous" if auth=="anonymous" else str(os.environ.get("DSM_STEAM_USER") or "").strip()
 if not login:raise RuntimeError("Steam authentication is required on this Agent")
 target.mkdir(parents=True,exist_ok=True);cp=subprocess.run([_steamcmd(),"+force_install_dir",str(target),"+login",login,"+app_update",app,"validate","+quit"],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=7200,check=False,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0));print(cp.stdout or "",end="",flush=True)
 if cp.returncode!=0:raise RuntimeError(f"SteamCMD failed with exit code {cp.returncode}")
def _download(url,dst):
 req=urllib.request.Request(url,headers={"User-Agent":"Capivara-Agent/1"})
 with urllib.request.urlopen(req,timeout=60) as src,open(dst,"wb") as out:shutil.copyfileobj(src,out,1024*1024)
def _verify(path,expected):
 e=str(expected or "").strip().lower()
 if not e:return
 h=hashlib.sha256()
 with open(path,"rb") as f:
  for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
 if h.hexdigest().lower()!=e:raise RuntimeError("download checksum mismatch")
def _safe_member(name):
 normalized=str(name or "").replace("\\","/");p=PurePosixPath(normalized)
 if p.is_absolute() or ".." in p.parts:raise RuntimeError("unsafe archive member")
def _run_http(sel,target):
 install=sel.get("install") if isinstance(sel.get("install"),dict) else {};asset=sel.get("asset") if isinstance(sel.get("asset"),dict) else {};url=str(asset.get("url") or install.get("url") or "")
 if not url.startswith(("https://","http://")):raise ValueError("HTTP artifact URL is missing or invalid")
 target.mkdir(parents=True,exist_ok=True)
 with tempfile.TemporaryDirectory(prefix="capivara-game-data-") as td:
  artifact=Path(td)/"artifact";_download(url,artifact);_verify(artifact,asset.get("sha256") or install.get("sha256"));staging=Path(td)/"extract"
  if zipfile.is_zipfile(artifact):
   staging.mkdir();z=zipfile.ZipFile(artifact)
   for i in z.infolist():_safe_member(i.filename)
   z.extractall(staging);z.close()
  elif tarfile.is_tarfile(artifact):
   staging.mkdir();t=tarfile.open(artifact,"r:*")
   for m in t.getmembers():
    _safe_member(m.name)
    if not (m.isfile() or m.isdir()):raise RuntimeError("unsupported archive member")
   t.extractall(staging);t.close()
  else:
   name=_safe(Path(str(asset.get("name") or install.get("asset") or sel.get("executable") or "artifact")).name,"artifact filename");shutil.copy2(artifact,target/name);return
  for entry in staging.iterdir():
   dst=target/entry.name
   if dst.exists():shutil.rmtree(dst) if dst.is_dir() else dst.unlink()
   shutil.move(str(entry),str(dst))
def _install(sel,target,provider):
 if provider=="steam":_run_steam(sel,target)
 elif provider in {"http","http-archive","github"}:_run_http(sel,target)
 else:raise RuntimeError(f"provider not supported by standalone Windows Agent: {provider}")
 execute_installer(sel,target)
def execute(command:dict[str,Any]):
 action=str(command.get("action") or "install").lower()
 if action=="install-steamcmd":return _install_steamcmd()
 sel=command.get("selection")
 if not isinstance(sel,dict):raise ValueError("runtime selection is missing")
 target=_target(sel);provider=str(sel.get("provider") or "").lower();reused=False
 if action=="ensure":
  if inspect_game_data(target,sel).get("health")=="ok":reused=True
  else:_install(sel,target,provider)
 elif action in {"install","update","repair"}:_install(sel,target,provider)
 elif action=="verify":pass
 elif action in FILE_ACTIONS:
  op=command.get("file_operation")
  if not isinstance(op,dict):raise ValueError("file operation payload is missing")
  if "file-"+str(op.get("action") or "").lower()!=action:raise ValueError("file operation action mismatch")
  return {"provider":provider,"game":sel.get("game"),"version":sel.get("version"),"target_path":str(target),"file_result":execute_file_operation(target,op)}
 else:raise ValueError("unsupported game-data action")
 integrity=inspect_game_data(target,sel)
 if action in {"ensure","verify"} and integrity.get("health")!="ok":raise RuntimeError(f"game-data integrity check failed: {integrity.get('health')}")
 return {"provider":provider,"game":sel.get("game"),"version":sel.get("version"),"target_path":str(target),"integrity":integrity,"reused":reused}
def main():
 if len(sys.argv)!=3:return 2
 req=Path(sys.argv[1]);res=Path(sys.argv[2]);command=json.loads(req.read_text(encoding="utf-8"));job=str(command.get("job_id") or "");action=str(command.get("action") or "install");write_json(res,{"job_id":job,"status":"running","progress":5})
 try:detail=execute(command)
 except Exception as exc:write_json(res,{"job_id":job,"status":"failed","progress":100,"error":str(exc)[:2000]});return 1
 out={"job_id":job,"status":"completed","progress":100,**detail};write_json(res,out);sel=command.get("selection") if isinstance(command.get("selection"),dict) else {}
 if action in {"ensure","install","update","verify","repair"}:record_game_data(job_id=job,action=action,selection=sel,result=out)
 return 0
if __name__=="__main__":raise SystemExit(main())
