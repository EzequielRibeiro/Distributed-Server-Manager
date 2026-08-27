"""Game profile orchestration for Windows Agent runtime materialization."""
from __future__ import annotations
import re
from pathlib import Path
from typing import Any
from catalog_runtime_policy import apply_policy
from profiles import resolve_profile
from runtime_spec import validate_runtime_spec
from storage_pools import resolve_storage_pool
_INSTANCE_ID=re.compile(r"^[A-Za-z0-9._-]{1,191}$")
def instance_state_root(config:dict[str,Any],instance_id:str,storage_pool_id:str|None=None)->Path:
 token=str(instance_id or "").strip()
 if not _INSTANCE_ID.fullmatch(token):raise ValueError("invalid instance_id")
 pool=resolve_storage_pool(config,storage_pool_id);root=Path(pool["root_path"]);path=(root/token).resolve(strict=False)
 try:path.relative_to(root.resolve(strict=False))
 except ValueError as exc:raise ValueError("instance path escapes Agent storage pool") from exc
 return path
def build_runtime_spec(config:dict[str,Any],instance:dict[str,Any],context:dict[str,Any])->dict[str,Any]:
 if not isinstance(instance,dict) or not isinstance(context,dict):raise ValueError("instance and runtime context must be objects")
 agent_id=str(config.get("agent_id") or "").strip()
 if not agent_id:raise ValueError("Agent identity is required")
 if str(instance.get("agent_id") or "").strip()!=agent_id:raise PermissionError("instance belongs to another Agent")
 instance_id=str(instance.get("instance_id") or instance.get("id") or "").strip();requested_pool=str(context.get("storage_pool_id") or instance.get("storage_pool_id") or "").strip() or None;pool=resolve_storage_pool(config,requested_pool);effective=dict(context);effective["storage_pool_id"]=pool["id"];effective.setdefault("instance_state_root",str(instance_state_root(config,instance_id,pool["id"])))
 raw=resolve_profile(instance).build_runtime_spec(dict(instance),effective);raw=apply_policy(raw,instance,effective);normalized=validate_runtime_spec(raw,expected_agent_id=agent_id);normalized["game_id"]=str(raw.get("game_id") or instance.get("game_id") or "").strip().lower();normalized["environment_id"]=str(raw.get("environment_id") or instance.get("environment_id") or "").strip();normalized["profile"]=str(raw.get("profile") or normalized["game_id"]);normalized["profile_version"]=int(raw.get("profile_version") or 1);normalized["storage_pool_id"]=pool["id"];normalized["instance_state_root"]=effective["instance_state_root"]
 for key in ("ports","config_path","catalog_runtime_policy","catalog_templates","catalog_network_properties","catalog_variables"):
  if key in raw:normalized[key]=raw[key]
 return normalized
__all__=["build_runtime_spec","instance_state_root"]
