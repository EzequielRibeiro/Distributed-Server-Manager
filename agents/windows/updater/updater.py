#!/usr/bin/env python3
"""Windows Agent self-updater using immutable GitHub Release packages."""
from __future__ import annotations
import hashlib,json,os,shutil,subprocess,sys,tempfile,time,urllib.request,zipfile
from pathlib import Path,PurePosixPath
PROGRAM_DATA=Path(os.environ.get("PROGRAMDATA",r"C:\ProgramData"));PROGRAM_FILES=Path(os.environ.get("ProgramFiles",r"C:\Program Files"));STATE_DIR=Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR",PROGRAM_DATA/"CapivaraAgent"/"state"));DATA_ROOT=STATE_DIR.parent;INSTALL_ROOT=Path(os.environ.get("CAPIVARA_AGENT_ROOT",PROGRAM_FILES/"CapivaraAgent"));REQUEST_PATH=STATE_DIR/"update-request.json";RESULT_PATH=STATE_DIR/"update-result.json";REPOSITORY=os.environ.get("CAPIVARA_AGENT_GITHUB_REPOSITORY","EzequielRibeiro/Distributed-Server-Manager");TASK_NAME=os.environ.get("CAPIVARA_AGENT_TASK_NAME","CapivaraAgent")
def _write_result(status:str,**extra):
 STATE_DIR.mkdir(parents=True,exist_ok=True);temp=RESULT_PATH.with_suffix(".tmp");temp.write_text(json.dumps({"status":status,**extra},indent=2,sort_keys=True)+"\n",encoding="utf-8");temp.replace(RESULT_PATH)
def _read_request()->dict:
 return json.loads(REQUEST_PATH.read_text(encoding="utf-8-sig"))
def _download(url:str,target:Path):
 request=urllib.request.Request(url,headers={"User-Agent":"Capivara-Agent-Windows-Updater"})
 with urllib.request.urlopen(request,timeout=60) as response,target.open("wb") as output:shutil.copyfileobj(response,output)
def _safe_extract(package:zipfile.ZipFile,destination:Path):
 for info in package.infolist():
  raw=info.filename;name=PurePosixPath(raw)
  if name.is_absolute() or ".." in name.parts or "\\" in raw or ":" in raw:raise RuntimeError(f"unsafe archive path: {raw}")
  target=destination.joinpath(*name.parts)
  if info.is_dir():target.mkdir(parents=True,exist_ok=True);continue
  target.parent.mkdir(parents=True,exist_ok=True)
  with package.open(info) as source,target.open("wb") as output:shutil.copyfileobj(source,output)
def _verify(package_root:Path,version:str)->dict:
 manifest=json.loads((package_root/"manifest.json").read_text(encoding="utf-8"))
 if manifest.get("kind")!="CapivaraAgentPackage" or manifest.get("platform")!="windows":raise RuntimeError("invalid Windows Agent package")
 if str(manifest.get("version"))!=version:raise RuntimeError("package version mismatch")
 for relative in manifest.get("required_files",[]):
  path=package_root/relative;expected=((manifest.get("files") or {}).get(relative) or {}).get("sha256")
  if not path.is_file() or not expected:raise RuntimeError(f"invalid package file: {relative}")
  if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:raise RuntimeError(f"internal checksum mismatch: {relative}")
 return manifest
def _destination(relative:str)->Path|None:
 path=PurePosixPath(relative)
 if relative.startswith("agent/runtime/") and path.suffix==".py":return INSTALL_ROOT/"runtime"/path.name
 if relative.startswith("agent/updater/") and path.suffix==".py":return INSTALL_ROOT/"updater"/path.name
 if relative.startswith("agent/common/") and path.suffix==".py":return INSTALL_ROOT/"common"/path.name
 if relative.startswith("service/") and path.suffix==".ps1":return INSTALL_ROOT/"service"/path.name
 if relative.startswith("gui/") and path.suffix==".ps1":return INSTALL_ROOT/"gui"/path.name
 if relative in {"manifest.json","VERSION"}:return INSTALL_ROOT/path.name
 return None
def _powershell(script:Path,*args:str)->subprocess.CompletedProcess:
 return subprocess.run(["powershell.exe","-NoProfile","-ExecutionPolicy","Bypass","-File",str(script),*map(str,args)],check=False,capture_output=True,text=True,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
def _stop_agent_task()->bool:
 command="$t=Get-ScheduledTask -TaskName $args[0] -ErrorAction SilentlyContinue; if ($null -ne $t -and $t.State -eq 'Running') { Stop-ScheduledTask -TaskName $args[0] -ErrorAction Stop; exit 10 }; exit 0"
 result=subprocess.run(["powershell.exe","-NoProfile","-Command",command,TASK_NAME],check=False,capture_output=True,text=True,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
 if result.returncode not in {0,10}:raise RuntimeError(f"failed to stop existing Windows Agent task: {(result.stderr or result.stdout)[-1500:]}")
 if result.returncode==10:time.sleep(2)
 return result.returncode==10
def _task_is_running()->bool:
 command="$t=Get-ScheduledTask -TaskName $args[0] -ErrorAction SilentlyContinue; if ($null -ne $t -and $t.State -eq 'Running') { exit 0 }; exit 1"
 result=subprocess.run(["powershell.exe","-NoProfile","-Command",command,TASK_NAME],check=False,capture_output=True,text=True,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
 return result.returncode==0
def _reconcile_runtime_integration()->dict:
 register=INSTALL_ROOT/"service"/"register-task.ps1";launcher=INSTALL_ROOT/"service"/"run-agent.ps1";agent=INSTALL_ROOT/"runtime"/"agent.py";gui=INSTALL_ROOT/"gui"/"install-gui.ps1"
 if not all(path.is_file() for path in (register,launcher,agent)):raise RuntimeError("updated Windows Agent service integration is incomplete")
 stopped=_stop_agent_task();task=_powershell(register,"-PythonExe",sys.executable,"-AgentScript",str(agent),"-TaskName",TASK_NAME,"-DataRoot",str(DATA_ROOT),"-LauncherScript",str(launcher))
 if task.returncode!=0:raise RuntimeError(f"failed to reconcile Windows Agent task: {(task.stderr or task.stdout)[-1500:]}")
 running=False
 for _ in range(10):
  if _task_is_running():running=True;break
  time.sleep(1)
 if not running:raise RuntimeError("updated Windows Agent task did not enter Running state")
 gui_enabled=None
 if gui.is_file():
  result=_powershell(gui,"-InstallRoot",str(INSTALL_ROOT),"-DataRoot",str(DATA_ROOT),"-GuiMode","auto")
  if result.returncode!=0:raise RuntimeError(f"failed to reconcile Windows Agent GUI: {(result.stderr or result.stdout)[-1500:]}")
  gui_enabled='"gui_enabled":true' in (result.stdout or "").replace(" ","").lower()
 return {"task_reconciled":True,"task_restarted":stopped,"task_running":running,"gui_enabled":gui_enabled}
def apply_request()->int:
 request=_read_request();version=str(request.get("desired_version","")).strip();channel=str(request.get("channel","stable")).strip().lower()
 if not version:raise RuntimeError("desired_version is required")
 if channel=="local/manual":raise RuntimeError("local/manual update requires an administrator supplied package")
 tag=version if version.startswith("v") else f"v{version}";plain=version[1:] if version.startswith("v") else version;archive_name=f"capivara-agent-windows-{plain}.zip";base=f"https://github.com/{REPOSITORY}/releases/download/{tag}"
 with tempfile.TemporaryDirectory(prefix="capivara-agent-win-update-") as tmp:
  work=Path(tmp);archive=work/archive_name;checksum=work/f"{archive_name}.sha256";_download(f"{base}/{archive_name}",archive);_download(f"{base}/{archive_name}.sha256",checksum);expected=checksum.read_text(encoding="utf-8").split()[0].strip().lower()
  if hashlib.sha256(archive.read_bytes()).hexdigest()!=expected:raise RuntimeError("release checksum mismatch")
  extract=work/"extract";extract.mkdir()
  with zipfile.ZipFile(archive) as package:_safe_extract(package,extract)
  package_root=extract/f"capivara-agent-windows-{plain}";manifest=_verify(package_root,plain)
  for relative in manifest.get("required_files",[]):
   destination=_destination(str(relative))
   if destination is None:continue
   source=package_root/str(relative);destination.parent.mkdir(parents=True,exist_ok=True);temporary=destination.with_suffix(destination.suffix+".new");shutil.copy2(source,temporary);os.replace(temporary,destination)
 integration=_reconcile_runtime_integration();REQUEST_PATH.unlink(missing_ok=True);_write_result("applied",installed_version=plain,rollout_id=request.get("rollout_id"),**integration);return 0
def main()->int:
 try:return apply_request()
 except Exception as exc:REQUEST_PATH.unlink(missing_ok=True);_write_result("failed",error=str(exc)[:2000]);subprocess.run(["schtasks","/Run","/TN",TASK_NAME],check=False,capture_output=True);return 1
if __name__=="__main__":raise SystemExit(main())
