"""Apply contract resource limits to game processes using Windows Job Objects."""
from __future__ import annotations
import ctypes,os
from ctypes import wintypes

_JOB_OBJECT_LIMIT_ACTIVE_PROCESS=0x00000008
_JOB_OBJECT_LIMIT_JOB_MEMORY=0x00000200
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE=0x00002000
_JOB_OBJECT_CPU_RATE_CONTROL_ENABLE=0x1
_JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP=0x4
_JobObjectExtendedLimitInformation=9
_JobObjectCpuRateControlInformation=15
_PROCESS_SET_QUOTA=0x0100
_PROCESS_TERMINATE=0x0001
_PROCESS_QUERY_LIMITED_INFORMATION=0x1000
_handles={}

class IO_COUNTERS(ctypes.Structure):
 _fields_=[("ReadOperationCount",ctypes.c_ulonglong),("WriteOperationCount",ctypes.c_ulonglong),("OtherOperationCount",ctypes.c_ulonglong),("ReadTransferCount",ctypes.c_ulonglong),("WriteTransferCount",ctypes.c_ulonglong),("OtherTransferCount",ctypes.c_ulonglong)]
class BASIC_LIMIT(ctypes.Structure):
 _fields_=[("PerProcessUserTimeLimit",ctypes.c_longlong),("PerJobUserTimeLimit",ctypes.c_longlong),("LimitFlags",wintypes.DWORD),("MinimumWorkingSetSize",ctypes.c_size_t),("MaximumWorkingSetSize",ctypes.c_size_t),("ActiveProcessLimit",wintypes.DWORD),("Affinity",ctypes.c_size_t),("PriorityClass",wintypes.DWORD),("SchedulingClass",wintypes.DWORD)]
class EXTENDED_LIMIT(ctypes.Structure):
 _fields_=[("BasicLimitInformation",BASIC_LIMIT),("IoInfo",IO_COUNTERS),("ProcessMemoryLimit",ctypes.c_size_t),("JobMemoryLimit",ctypes.c_size_t),("PeakProcessMemoryUsed",ctypes.c_size_t),("PeakJobMemoryUsed",ctypes.c_size_t)]
class CPU_RATE(ctypes.Structure):
 _fields_=[("ControlFlags",wintypes.DWORD),("CpuRate",wintypes.DWORD)]

def _raise(label):raise OSError(ctypes.get_last_error(),label)
def apply_process_limits(pid:int,spec:dict):
 if os.name!="nt":return None
 kernel=ctypes.WinDLL("kernel32",use_last_error=True);job=kernel.CreateJobObjectW(None,None)
 if not job:_raise("CreateJobObjectW")
 info=EXTENDED_LIMIT();info.BasicLimitInformation.LimitFlags=_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
 memory=spec.get("memory_limit_bytes")
 if memory is not None:
  value=int(memory)
  if value<64*1024*1024:raise ValueError("memory_limit_bytes is below safe minimum")
  info.BasicLimitInformation.LimitFlags|=_JOB_OBJECT_LIMIT_JOB_MEMORY;info.JobMemoryLimit=value
 pids=spec.get("pids_limit")
 if pids is not None:
  value=int(pids)
  if value<1:raise ValueError("pids_limit must be positive")
  info.BasicLimitInformation.LimitFlags|=_JOB_OBJECT_LIMIT_ACTIVE_PROCESS;info.BasicLimitInformation.ActiveProcessLimit=value
 if not kernel.SetInformationJobObject(job,_JobObjectExtendedLimitInformation,ctypes.byref(info),ctypes.sizeof(info)):_raise("SetInformationJobObject limits")
 cpu=spec.get("cpu_limit_cores")
 if cpu is not None:
  cores=float(cpu);host=max(1,int(os.cpu_count() or 1))
  if cores<=0:raise ValueError("cpu_limit_cores must be positive")
  rate=max(1,min(10000,int(round((cores/host)*10000))))
  cpuinfo=CPU_RATE(_JOB_OBJECT_CPU_RATE_CONTROL_ENABLE|_JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP,rate)
  if not kernel.SetInformationJobObject(job,_JobObjectCpuRateControlInformation,ctypes.byref(cpuinfo),ctypes.sizeof(cpuinfo)):_raise("SetInformationJobObject CPU")
 process=kernel.OpenProcess(_PROCESS_SET_QUOTA|_PROCESS_TERMINATE|_PROCESS_QUERY_LIMITED_INFORMATION,False,int(pid))
 if not process:_raise("OpenProcess")
 try:
  if not kernel.AssignProcessToJobObject(job,process):_raise("AssignProcessToJobObject")
 finally:kernel.CloseHandle(process)
 old=_handles.pop(int(pid),None)
 if old:kernel.CloseHandle(old)
 _handles[int(pid)]=job
 return {"pid":int(pid),"memory_limit_bytes":int(memory) if memory is not None else None,"cpu_limit_cores":float(cpu) if cpu is not None else None,"pids_limit":int(pids) if pids is not None else None}
def release_process(pid:int):
 if os.name!="nt":return
 handle=_handles.pop(int(pid),None)
 if handle:ctypes.WinDLL("kernel32",use_last_error=True).CloseHandle(handle)

__all__=["apply_process_limits","release_process"]
