#!/usr/bin/env python3
"""Allowlisted Agent-local executor for Controller YARA-X administration."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from content_client import content_state
from content_security import scan_content
from security_yarax import install as install_engine, status as engine_status
from security_yarax_rules import install as install_rules, rollback as rollback_rules, status as rules_status

STATE_DIR = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", Path(os.environ.get("PROGRAMDATA", r"C:\\ProgramData")) / "CapivaraAgent" / "state"))
RESULT_PATH = STATE_DIR / "security" / "yara-x" / "admin-result.json"
ACTIONS = frozenset({"install_engine","install_rules","test_scan","rescan_content","rollback_rules"})
EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


def _write_result(payload: dict[str, Any]) -> None:
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp=RESULT_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(payload,indent=2,sort_keys=True,default=str)+"\n",encoding="utf-8")
    os.replace(temp,RESULT_PATH)


def read_result()->dict[str,Any]|None:
    try:value=json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    except (OSError,ValueError,json.JSONDecodeError):return None
    return value if isinstance(value,dict) else None


def clear_result(operation_id:str|None=None)->None:
    current=read_result()
    if operation_id and isinstance(current,dict) and str(current.get("operation_id") or "")!=str(operation_id):
        return
    try:RESULT_PATH.unlink()
    except FileNotFoundError:pass


def _rescan(command:dict[str,Any])->dict[str,Any]:
    iid=str(command.get("instance_id") or "").strip();cid=str(command.get("content_id") or "").strip()
    if not iid or not cid:raise ValueError("rescan_content requires instance_id and content_id")
    record=next((x for x in content_state() if str(x.get("instance_id") or "")==iid and str(x.get("content_id") or "")==cid),None)
    if not isinstance(record,dict):raise LookupError("managed content state not found")
    path=Path(str(record.get("managed_path") or ""))
    if not path.exists():raise FileNotFoundError("managed content path is unavailable")
    verdict=scan_content(path,context={
        "agent_id":command.get("agent_id"),
        "instance_id":iid,
        "content_id":cid,
        "provider":record.get("provider"),
        "game_id":record.get("game_id"),
    })
    return {"verdict":verdict,"instance_id":iid,"content_id":cid}


def _test_scan(command:dict[str,Any])->dict[str,Any]:
    STATE_DIR.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".yarax-test-",dir=str(STATE_DIR)) as td:
        target=Path(td)/"eicar.txt";target.write_bytes(EICAR)
        verdict=scan_content(target,context={"agent_id":command.get("agent_id"),"content_id":"yarax-self-test"})
    if str(verdict.get("security_state") or "")!="blocked":
        raise RuntimeError("YARA-X self-test did not block the EICAR validation payload")
    return {"self_test":"passed","verdict":verdict}


def handle_command(command:dict[str,Any])->dict[str,Any]:
    if not isinstance(command,dict):raise ValueError("YARA-X operation must be an object")
    operation_id=str(command.get("operation_id") or "").strip();action=str(command.get("action") or "").strip().lower()
    if not operation_id or action not in ACTIONS:raise ValueError("invalid YARA-X administrative operation")
    existing=read_result()
    if isinstance(existing,dict) and str(existing.get("operation_id") or "")==operation_id and str(existing.get("status") or "") in {"completed","failed"}:
        return existing
    result={"operation_id":operation_id,"action":action,"status":"running"}
    _write_result(result)
    try:
        if action=="install_engine":details=install_engine()
        elif action=="install_rules":details=install_rules()
        elif action=="test_scan":details=_test_scan(command)
        elif action=="rescan_content":details=_rescan(command)
        else:details=rollback_rules()
        result={"operation_id":operation_id,"action":action,"status":"completed","details":details,"engine":engine_status(),"rules":rules_status()}
    except Exception as exc:
        result={"operation_id":operation_id,"action":action,"status":"failed","error":str(exc)[:2000],"engine":engine_status(),"rules":rules_status()}
    _write_result(result);return result


__all__=["ACTIONS","clear_result","handle_command","read_result"]
