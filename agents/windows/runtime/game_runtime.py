"""Game profile orchestration for Windows Agent runtime materialization."""
from __future__ import annotations
from typing import Any
from catalog_runtime_policy import apply_policy
from profiles import resolve_profile
from runtime_spec import validate_runtime_spec

def build_runtime_spec(config:dict[str,Any],instance:dict[str,Any],context:dict[str,Any])->dict[str,Any]:
 if not isinstance(instance,dict) or not isinstance(context,dict):raise ValueError("instance and runtime context must be objects")
 agent_id=str(config.get("agent_id") or "").strip()
 if not agent_id:raise ValueError("Agent identity is required")
 if str(instance.get("agent_id") or "").strip()!=agent_id:raise PermissionError("instance belongs to another Agent")
 raw=resolve_profile(instance).build_runtime_spec(dict(instance),dict(context));raw=apply_policy(raw,instance,context);normalized=validate_runtime_spec(raw,expected_agent_id=agent_id);normalized["game_id"]=str(raw.get("game_id") or instance.get("game_id") or "").strip().lower();normalized["environment_id"]=str(raw.get("environment_id") or instance.get("environment_id") or "").strip();normalized["profile"]=str(raw.get("profile") or normalized["game_id"]);normalized["profile_version"]=int(raw.get("profile_version") or 1)
 for key in ("ports","config_path","catalog_runtime_policy","catalog_templates","catalog_network_properties","catalog_variables"):
  if key in raw:normalized[key]=raw[key]
 return normalized
__all__=["build_runtime_spec"]
