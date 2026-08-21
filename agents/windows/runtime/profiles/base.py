"""Contract and helpers for Windows game runtime profiles."""
from __future__ import annotations
from abc import ABC,abstractmethod
from pathlib import Path
from typing import Any
class ProfileError(ValueError):pass
def require_text(value:Any,label:str)->str:
 text=str(value or "").strip()
 if not text or any(c in text for c in ("\x00","\n","\r")):raise ProfileError(f"invalid {label}")
 return text
def require_absolute(value:Any,label:str)->str:
 text=require_text(value,label);p=Path(text)
 if not p.is_absolute():raise ProfileError(f"invalid {label}")
 return str(p)
def require_within(root:Any,value:Any,label:str)->str:
 root_path=Path(require_absolute(root,"install_path")).resolve(strict=False);value_path=Path(require_absolute(value,label)).resolve(strict=False)
 try:value_path.relative_to(root_path)
 except ValueError as exc:raise ProfileError(f"{label} escapes provisioned content root") from exc
 return str(value_path)
def port_bindings(context:dict[str,Any])->dict[str,dict[str,Any]]:
 raw=context.get("ports",{});entries=[]
 if isinstance(raw,dict):
  for role,item in raw.items():entries.append({"role":role,**item} if isinstance(item,dict) else {"role":role,"port":item})
 elif isinstance(raw,list):entries=raw
 else:raise ProfileError("invalid reserved ports")
 values={}
 for item in entries:
  if not isinstance(item,dict):raise ProfileError("invalid reserved port entry")
  role=require_text(item.get("role") or item.get("name") or item.get("purpose"),"port role").lower()
  try:port=int(item.get("port"))
  except (TypeError,ValueError) as exc:raise ProfileError(f"invalid reserved port for role: {role}") from exc
  protocol=str(item.get("protocol") or "udp").lower()
  if role in values or port<1 or port>65535 or protocol not in {"tcp","udp"}:raise ProfileError(f"invalid reserved port for role: {role}")
  values[role]={"port":port,"protocol":protocol}
 return values
def require_port(context:dict[str,Any],role:str,*,protocol:str|None=None)->int:
 binding=port_bindings(context).get(role)
 if binding is None:raise ProfileError(f"required reserved port is missing: {role}")
 if protocol and binding["protocol"]!=protocol:raise ProfileError(f"reserved port protocol mismatch for role: {role}")
 return int(binding["port"])
class GameRuntimeProfile(ABC):
 game_ids:tuple[str,...]=()
 @abstractmethod
 def build_runtime_spec(self,instance:dict[str,Any],context:dict[str,Any])->dict[str,Any]:raise NotImplementedError
__all__=["GameRuntimeProfile","ProfileError","port_bindings","require_absolute","require_port","require_text","require_within"]
