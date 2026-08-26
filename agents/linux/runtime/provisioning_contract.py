#!/usr/bin/env python3
"""Validate B10 Agent-local instance provisioning requests."""
from __future__ import annotations
import re
from typing import Any
_TOKEN=re.compile(r"^[A-Za-z0-9._-]{1,191}$")
VALID_DESIRED_STATES={"running","stopped"}
VALID_CONTENT_ACTIONS={"ensure","install","update","verify"}
class ProvisioningContractError(ValueError):pass
def _token(value:Any,label:str)->str:
 text=str(value or "").strip()
 if not _TOKEN.fullmatch(text):raise ProvisioningContractError(f"invalid {label}")
 return text
def validate_provisioning_request(request:dict[str,Any],*,expected_agent_id:str)->dict[str,Any]:
 if not isinstance(request,dict):raise ProvisioningContractError("provisioning request must be an object")
 result=dict(request);result["schema_version"]=1;result["kind"]="CapivaraInstanceProvisioningRequest";result["provisioning_id"]=_token(result.get("provisioning_id"),"provisioning_id");result["agent_id"]=_token(result.get("agent_id"),"agent_id");expected=_token(expected_agent_id,"expected_agent_id")
 if result["agent_id"]!=expected:raise ProvisioningContractError("provisioning request belongs to another Agent")
 result["instance_id"]=_token(result.get("instance_id"),"instance_id");result["environment_id"]=_token(result.get("environment_id"),"environment_id");result["selector"]=_token(result.get("selector"),"selector");desired=str(result.get("desired_state") or "stopped").strip().lower()
 if desired not in VALID_DESIRED_STATES:raise ProvisioningContractError("invalid desired_state")
 result["desired_state"]=desired;instance=result.get("instance")
 if not isinstance(instance,dict):raise ProvisioningContractError("instance contract is required")
 instance=dict(instance)
 if _token(instance.get("instance_id"),"instance.instance_id")!=result["instance_id"]:raise ProvisioningContractError("instance_id mismatch")
 if _token(instance.get("agent_id"),"instance.agent_id")!=expected:raise ProvisioningContractError("instance belongs to another Agent")
 instance["game_id"]=_token(instance.get("game_id"),"instance.game_id").lower();instance["environment_id"]=_token(instance.get("environment_id") or result["environment_id"],"instance.environment_id");instance["runtime_id"]=_token(instance.get("runtime_id") or result["instance_id"],"instance.runtime_id");instance["desired_state"]=desired
 if instance.get("storage_pool_id") is not None:instance["storage_pool_id"]=_token(instance.get("storage_pool_id"),"instance.storage_pool_id")
 if instance.get("storage_reserved_bytes") is not None:
  try:reserved=int(instance.get("storage_reserved_bytes"))
  except (TypeError,ValueError) as exc:raise ProvisioningContractError("invalid instance.storage_reserved_bytes") from exc
  if reserved<0:raise ProvisioningContractError("invalid instance.storage_reserved_bytes")
  if reserved and not instance.get("storage_pool_id"):raise ProvisioningContractError("storage reservation requires storage_pool_id")
  instance["storage_reserved_bytes"]=reserved
 result["instance"]=instance
 content=result.get("content")
 if not isinstance(content,dict) or not isinstance(content.get("selection"),dict) or not content.get("selection"):raise ProvisioningContractError("content selection is required")
 content=dict(content);action=str(content.get("action") or "ensure").strip().lower()
 if action not in VALID_CONTENT_ACTIONS:raise ProvisioningContractError("invalid content action")
 content["action"]=action;content["selection"]=dict(content["selection"]);result["content"]=content
 ports=result.get("ports")
 if not isinstance(ports,dict) or not ports:raise ProvisioningContractError("reserved ports are required")
 normalized_ports={}
 for role,item in ports.items():
  role_name=_token(str(role).lower(),"port role")
  if not isinstance(item,dict):raise ProvisioningContractError("invalid reserved port entry")
  try:port=int(item.get("port"))
  except (TypeError,ValueError) as exc:raise ProvisioningContractError(f"invalid reserved port: {role_name}") from exc
  if not 1<=port<=65535:raise ProvisioningContractError(f"invalid reserved port: {role_name}")
  protocol=str(item.get("protocol") or "udp").strip().lower()
  if protocol not in {"tcp","udp"}:raise ProvisioningContractError(f"invalid reserved port protocol: {role_name}")
  normalized_ports[role_name]={"port":port,"protocol":protocol,"bind_address":str(item.get("bind_address") or "0.0.0.0")}
 result["ports"]=normalized_ports;configuration=result.get("configuration") or {}
 if not isinstance(configuration,dict):raise ProvisioningContractError("configuration must be an object")
 for forbidden in ("shell","command","argv","unit","service"):
  if forbidden in configuration:raise ProvisioningContractError(f"forbidden provisioning configuration field: {forbidden}")
 result["configuration"]=dict(configuration);return result
__all__=["ProvisioningContractError","VALID_CONTENT_ACTIONS","validate_provisioning_request"]
