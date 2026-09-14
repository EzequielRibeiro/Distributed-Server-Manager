#!/usr/bin/env python3
"""Detect primitive execution capabilities on Windows Agents."""
from __future__ import annotations
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from profiles.registry import supported_profiles
try:
    from content_security import scanner_status
except ModuleNotFoundError:
    import importlib.util as _importlib_util
    _security_spec=_importlib_util.spec_from_file_location("_capivara_content_security",Path(__file__).with_name("content_security.py"))
    if _security_spec is None or _security_spec.loader is None:raise
    _security_module=_importlib_util.module_from_spec(_security_spec);_security_spec.loader.exec_module(_security_module);scanner_status=_security_module.scanner_status

_JAVA_VERSION=re.compile(r'version\s+"([^"]+)"',re.IGNORECASE)
_BASE_CONTENT_PROVIDERS=("curseforge","github","http","http-archive","local","modrinth")

def _managed_steamcmd()->Path:
 return Path(os.environ.get("PROGRAMDATA") or r"C:\ProgramData")/"CapivaraAgent"/"tools"/"steamcmd"/"steamcmd.exe"

def _normalize_architecture(value:str|None=None)->str:
 machine=str(value or platform.machine() or "").strip().lower()
 aliases={"amd64":"x86_64","x86_64":"x86_64","arm64":"aarch64","aarch64":"aarch64","x86":"x86_32","i386":"x86_32","i686":"x86_32"}
 return aliases.get(machine,machine or "unknown")

def _java_major(version:str)->int|None:
 token=str(version or "").strip()
 if not token:return None
 parts=token.split(".")
 try:
  return int(parts[1]) if parts[0]=="1" and len(parts)>1 else int(parts[0])
 except ValueError:return None

def _java_status()->dict[str,object]:
 executable=shutil.which("java.exe") or shutil.which("java")
 if not executable:return {"installed":False,"functional":False,"state":"missing","path":None,"version":None,"major":None}
 result:dict[str,object]={"installed":True,"functional":False,"state":"error","path":executable,"version":None,"major":None}
 try:
  completed=subprocess.run([executable,"-version"],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=15,check=False,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
  output=completed.stdout or "";match=_JAVA_VERSION.search(output);version=match.group(1) if match else None;major=_java_major(version or "")
  functional=completed.returncode==0 and major is not None
  result.update(functional=functional,state="ready" if functional else "error",version=version,major=major)
  if not functional:result["error"]=output[-1000:] or f"java -version failed with exit code {completed.returncode}"
 except Exception as exc:result["error"]=str(exc)[:1000]
 return result

def detect_capabilities()->dict[str,object]:
 steamcmd=shutil.which("steamcmd.exe") is not None or shutil.which("steamcmd") is not None or _managed_steamcmd().is_file()
 content_providers=list(_BASE_CONTENT_PROVIDERS)
 if steamcmd:content_providers.extend(("steam","steam-workshop"))
 java_status=_java_status();java=bool(java_status["functional"]);content_security=scanner_status()
 return {
  "platform":{"os":"windows","architecture":_normalize_architecture()},
  "runtime_profiles":list(supported_profiles()),
  "content_provider_contract":1,
  "content_providers":content_providers,
  "content_security_contract":1,
  "content_security":content_security,
  "native-windows":True,
  "powershell":shutil.which("powershell") is not None or shutil.which("pwsh") is not None,
  "steamcmd":steamcmd,
  "java":java,
  "java_status":java_status,
  "docker":shutil.which("docker.exe") is not None or shutil.which("docker") is not None,
  "wine":False,
  "backup":True,
  "mod-management":True,
 }

__all__=["detect_capabilities"]
