"""Per-instance process lock used to serialize Windows Agent runtime operations."""
from __future__ import annotations
from contextlib import contextmanager
import json,os,time
from pathlib import Path
from typing import Any,Iterator
import instance_runtime
class RuntimeLockTimeout(RuntimeError):pass
def _root():return Path(instance_runtime.STATE_DIR)/"instance-locks"
def _token(value:Any)->str:
 text=str(value or "").strip();allowed="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
 if not text or len(text)>191 or any(ch not in allowed for ch in text):raise ValueError("invalid instance_id")
 return text
def _try_lock(fd:int)->bool:
 if os.name=="nt":
  import msvcrt
  try:os.lseek(fd,0,os.SEEK_SET);msvcrt.locking(fd,msvcrt.LK_NBLCK,1);return True
  except OSError:return False
 import fcntl
 try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);return True
 except BlockingIOError:return False
def _unlock(fd:int)->None:
 try:
  if os.name=="nt":
   import msvcrt;os.lseek(fd,0,os.SEEK_SET);msvcrt.locking(fd,msvcrt.LK_UNLCK,1)
  else:
   import fcntl;fcntl.flock(fd,fcntl.LOCK_UN)
 except OSError:pass
@contextmanager
def instance_lock(instance_id:str,operation:str,*,timeout_seconds:float=5.0)->Iterator[dict[str,Any]]:
 instance_id=_token(instance_id);operation=str(operation or "").strip()
 if not operation:raise ValueError("operation is required")
 root=_root();root.mkdir(parents=True,exist_ok=True);path=root/f"{instance_id}.lock";fd=os.open(path,os.O_RDWR|os.O_CREAT,0o600)
 if os.path.getsize(path)==0:os.write(fd,b"0")
 started=time.monotonic();acquired=False
 try:
  while not acquired:
   acquired=_try_lock(fd)
   if not acquired:
    if time.monotonic()-started>=max(0.0,float(timeout_seconds)):raise RuntimeLockTimeout(f"instance operation lock timeout: {instance_id}")
    time.sleep(.05)
  metadata={"schema_version":1,"kind":"CapivaraInstanceOperationLock","instance_id":instance_id,"operation":operation,"pid":os.getpid(),"acquired_monotonic":time.monotonic()};os.lseek(fd,0,os.SEEK_SET);os.ftruncate(fd,0);os.write(fd,(json.dumps(metadata,sort_keys=True)+"\n").encode("utf-8"));os.fsync(fd);yield metadata
 finally:
  if acquired:_unlock(fd)
  os.close(fd)
__all__=["RuntimeLockTimeout","instance_lock"]
