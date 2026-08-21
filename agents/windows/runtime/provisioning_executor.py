"""Execute a complete provisioning pipeline on the owning Windows Agent."""
from __future__ import annotations
import json,sys,time
from pathlib import Path
from typing import Any
from game_data_executor import execute as execute_game_data
import game_runtime,instance_runtime,runtime_materialization
from provisioning_state import write_json
from runtime_events import emit_runtime_event
from runtime_metrics import increment
PROGRAM_STEP_TIMEOUT=7200

def _event(event_type:str,instance:dict[str,Any],request:dict[str,Any],data:dict[str,Any]|None=None)->None:
 emit_runtime_event(Path(instance_runtime.STATE_DIR),event_type,agent_id=instance["agent_id"],instance_id=instance["instance_id"],data={"provisioning_id":request["provisioning_id"],**dict(data or {})})
def _result(path:Path,req:dict[str,Any],*,status:str,current_step:str,progress:int,**extra):
 payload={"provisioning_id":req["provisioning_id"],"instance_id":req["instance_id"],"status":status,"current_step":current_step,"progress":progress,**extra};write_json(path,payload);return payload
def _validate(config,request):
 for key in ("provisioning_id","instance_id"):
  if not str(request.get(key) or "").strip():raise ValueError(f"{key} is required")
 agent=str(config.get("agent_id") or "").strip();requested=str(request.get("agent_id") or agent).strip()
 if not agent or requested!=agent:raise PermissionError("provisioning belongs to another Agent")
 instance=request.get("instance")
 if not isinstance(instance,dict):raise ValueError("instance is required")
 return {**instance,"instance_id":request["instance_id"],"agent_id":agent,"desired_state":request.get("desired_state") or instance.get("desired_state") or "stopped"}
def execute(config:dict[str,Any],request:dict[str,Any],result_path:Path)->dict[str,Any]:
 instance=_validate(config,request);step="accepted";started=time.monotonic();materialized=False
 _result(result_path,request,status="running",current_step=step,progress=5);_event("INSTANCE_PROVISIONING_STARTED",instance,request)
 try:
  step="install_content";_result(result_path,request,status="running",current_step=step,progress=25);content=request.get("content") if isinstance(request.get("content"),dict) else {};selection=content.get("selection") if isinstance(content.get("selection"),dict) else None
  if selection is not None:content_result=execute_game_data({"action":content.get("action") or "install","selection":selection})
  else:
   configured=request.get("configuration") if isinstance(request.get("configuration"),dict) else {};install_path=str(configured.get("install_path") or instance.get("path") or "").strip()
   if not install_path:raise ValueError("provisioning content selection or install_path is required")
   content_result={"provider":"preinstalled","game":instance.get("game_id"),"version":None,"target_path":install_path}
  if time.monotonic()-started>PROGRAM_STEP_TIMEOUT:raise TimeoutError("provisioning timeout exceeded")
  step="build_runtime_spec";_result(result_path,request,status="running",current_step=step,progress=65);context=dict(request.get("configuration") or {});context["install_path"]=content_result["target_path"];context["content_root"]=content_result["target_path"];context["ports"]=request.get("ports") or context.get("ports") or {};context["desired_state"]=instance.get("desired_state");spec=game_runtime.build_runtime_spec(config,instance,context)
  step="materialize_runtime";_result(result_path,request,status="running",current_step=step,progress=82);materialization=runtime_materialization.materialize(config,spec);materialized=True
  step="initial_reconcile";_result(result_path,request,status="running",current_step=step,progress=92);reconciliation=runtime_materialization.reconcile(config,instance["instance_id"]);observed=str(reconciliation.get("observed_state") or "unknown")
  final=_result(result_path,request,status="completed",current_step="completed",progress=100,desired_state=spec["desired_state"],observed_state=observed,content={"provider":content_result.get("provider"),"game":content_result.get("game"),"version":content_result.get("version"),"target_path":content_result.get("target_path")},runtime={"profile":spec.get("profile"),"profile_version":spec.get("profile_version"),"adapter":spec.get("adapter"),"runtime_id":spec.get("runtime_id"),"materialized_changed":bool((materialization.get("operation") or {}).get("changed"))});increment("provisioning_completed");_event("INSTANCE_PROVISIONING_COMPLETED",instance,request,{"observed_state":observed});return final
 except Exception as exc:
  if materialized:
   try:runtime_materialization.remove(config,instance["instance_id"])
   except Exception:pass
  increment("provisioning_failed");failed=_result(result_path,request,status="failed",current_step=step,progress=100,error=str(exc)[:2000],compensation=["content_preserved_for_retry","port_reservations_preserved"]);_event("INSTANCE_PROVISIONING_FAILED",instance,request,{"error":str(exc)[:2000]});return failed
def main()->int:
 if len(sys.argv)!=4:return 2
 config=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"));request=json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"));result=execute(config,request,Path(sys.argv[3]));return 0 if result.get("status")=="completed" else 1
if __name__=="__main__":raise SystemExit(main())
