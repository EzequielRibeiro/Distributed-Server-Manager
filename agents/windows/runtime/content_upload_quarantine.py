"""Quarantine contract for customer-supplied content archives on Windows Agents."""
from __future__ import annotations
import os,stat,tarfile,zipfile
from pathlib import Path
from typing import Iterable
PROGRAM_DATA=Path(os.environ.get("PROGRAMDATA",r"C:\ProgramData"));GAME_DATA_ROOT=Path(os.environ.get("CAPIVARA_AGENT_GAME_DATA_ROOT",PROGRAM_DATA/"CapivaraAgent"/"state"/"game-data")).resolve();QUARANTINE_ROOT=(GAME_DATA_ROOT/"quarantine").resolve();_MAX_ENTRIES=100000;_MAX_EXPANDED=128*1024*1024*1024;_ALLOWED_SUFFIXES=(".zip",".tar",".tar.gz",".tgz")
def _token(value):
 text=str(value or "").strip()
 if not text or len(text)>191 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for c in text):raise ValueError("invalid quarantine token")
 return text
def _filename(value):
 raw=str(value or "");name=Path(raw).name
 if not name or name in {".",".."} or name!=raw:raise ValueError("invalid content upload filename")
 if not name.lower().endswith(_ALLOWED_SUFFIXES):raise ValueError("unsupported content archive")
 return name
def quarantine_destination(transfer_id,filename):
 candidate=(QUARANTINE_ROOT/_token(transfer_id)/_filename(filename)).resolve();candidate.relative_to(QUARANTINE_ROOT);return candidate
def _member_path(name):
 text=str(name or "").replace("\\","/");path=Path(text)
 if not text or text.startswith("/") or path.is_absolute() or any(part in {"",".",".."} for part in path.parts):raise ValueError("unsafe content archive path")
def _bounded(entries:Iterable[int]):
 total=0;count=0
 for size in entries:
  count+=1;total+=max(0,int(size or 0))
  if count>_MAX_ENTRIES:raise ValueError("content archive has too many entries")
  if total>_MAX_EXPANDED:raise ValueError("content archive expands beyond safety limit")
def validate_quarantine_archive(path:Path)->dict:
 archive=Path(path).resolve();archive.relative_to(QUARANTINE_ROOT)
 if not archive.is_file() or archive.is_symlink():raise ValueError("quarantined content archive is unavailable")
 if zipfile.is_zipfile(archive):
  with zipfile.ZipFile(archive) as handle:
   entries=handle.infolist();_bounded(item.file_size for item in entries)
   for item in entries:
    _member_path(item.filename);mode=(item.external_attr>>16)&0xFFFF
    if stat.S_ISLNK(mode):raise ValueError("content archive contains a symbolic link")
  return {"archive_type":"zip","entries":len(entries)}
 if tarfile.is_tarfile(archive):
  with tarfile.open(archive) as handle:
   entries=handle.getmembers();_bounded(item.size for item in entries)
   for item in entries:
    _member_path(item.name)
    if not (item.isfile() or item.isdir()) or item.issym() or item.islnk():raise ValueError("content archive contains an unsafe member")
  return {"archive_type":"tar","entries":len(entries)}
 raise ValueError("unsupported content archive format")
def quarantine_relative_path(path:Path)->str:return Path(path).resolve().relative_to(GAME_DATA_ROOT).as_posix()
__all__=["GAME_DATA_ROOT","QUARANTINE_ROOT","quarantine_destination","quarantine_relative_path","validate_quarantine_archive"]
