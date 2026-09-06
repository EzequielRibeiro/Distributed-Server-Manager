"""ARK: Survival Ascended Windows runtime with a fully private runtime tree."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from .base import GameRuntimeProfile,ProfileError,port_bindings,require_absolute,require_text

class ArkSurvivalAscendedRuntimeProfile(GameRuntimeProfile):
 game_ids=("arksurvivalascended","arksurvivalascended.stable");profile_version=1
 def build_runtime_spec(self,instance:dict[str,Any],context:dict[str,Any])->dict[str,Any]:
  iid=require_text(instance.get("instance_id") or instance.get("id"),"instance_id");aid=require_text(instance.get("agent_id"),"agent_id");eid=require_text(instance.get("environment_id") or "arksurvivalascended.stable","environment_id")
  install=require_absolute(context.get("install_path") or context.get("content_root") or instance.get("path"),"install_path");state=require_absolute(context.get("instance_state_root"),"instance_state_root")
  policy=context.get("catalog_runtime_policy")
  if not isinstance(policy,dict) or str(policy.get("runtime_id") or "").strip()!=eid:raise ProfileError("matching Catalog runtime policy is required for ARK Survival Ascended")
  ports=port_bindings(context)
  for role in ("game","query"):
   if role not in ports or ports[role].get("protocol")!="udp":raise ProfileError(f"ARK Survival Ascended requires UDP reservation: {role}")
  runtime=str(Path(state)/"runtime");exe=str(Path(runtime)/"ShooterGame"/"Binaries"/"Win64"/"ArkAscendedServer.exe")
  policy["executable"]=exe;policy["arguments"]=[]
  launch=f"TheIsland_WP?Port={ports['game']['port']}?QueryPort={ports['query']['port']}"
  extra=context.get("arguments") or []
  if not isinstance(extra,list):raise ProfileError("invalid ARK Survival Ascended arguments")
  args=[launch,*[str(x) for x in extra]]
  if any("\x00" in x or "\n" in x or "\r" in x for x in args):raise ProfileError("invalid ARK Survival Ascended argument")
  return {"instance_id":iid,"agent_id":aid,"game_id":"arksurvivalascended","environment_id":eid,"runtime_id":str(instance.get("runtime_id") or iid),"adapter":"windows-process","working_directory":runtime,"executable":exe,"executable_scope":"working-directory","arguments":args,"environment":{"CAPIVARA_INSTANCE_ID":iid,"CAPIVARA_GAME_ID":"arksurvivalascended"},"desired_state":str(instance.get("desired_state") or context.get("desired_state") or "stopped"),"profile":"ark-survival-ascended","profile_version":self.profile_version,"ports":ports,"instance_state_root":state,"configuration_root":str(Path(runtime)/"ShooterGame"/"Saved"/"Config"/"WindowsServer"),"writable_directories":[],"seed_source_root":install,"seed_files":[],"seed_directories":[{"source":install,"target":runtime}]}

__all__=["ArkSurvivalAscendedRuntimeProfile"]
