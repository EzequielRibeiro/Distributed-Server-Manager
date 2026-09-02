#!/usr/bin/env python3
"""Detect primitive execution capabilities on Windows Agents."""
from __future__ import annotations
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path

_JAVA_VERSION=re.compile(r'version\s+"([^"]+)"',re.IGNORECASE)

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
 java_status=_java_status();java=bool(java_status["functional"])
 return {
  "platform":{"os":"windows","architecture":_normalize_architecture()},
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
