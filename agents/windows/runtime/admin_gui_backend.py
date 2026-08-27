#!/usr/bin/env python3
"""Local administrative backend shared by the Windows Agent GUI and CLI console.

This module deliberately exposes only allowlisted Agent-local operations. It never
prints enrollment credentials or executes arbitrary shell commands.
"""
from __future__ import annotations
import json, os, socket, subprocess, sys, urllib.error, urllib.request
from pathlib import Path
from typing import Any

import instance_runtime
from capabilities import detect_capabilities
from configuration_client import configuration_state
from content_client import content_state
from backup_client import backup_state
from broadcast_client import broadcast_state
from game_data_state import summary as game_data_summary
from network_inventory import collect_network_inventory
from runtime_health import health_inventory
from runtime_metrics import snapshot as metrics_snapshot
from runtime_reconciler import reconcile_all, reconciliation_inventory
from storage_pools import pool_inventory

PROGRAM_DATA = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
STATE_DIR = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", PROGRAM_DATA / "CapivaraAgent" / "state"))
CONFIG_PATH = Path(os.environ.get("CAPIVARA_AGENT_CONFIG", PROGRAM_DATA / "CapivaraAgent" / "agent.json"))
LOG_PATH = Path(os.environ.get("CAPIVARA_AGENT_LOG", PROGRAM_DATA / "CapivaraAgent" / "logs" / "agent.log"))
TASK_NAME = os.environ.get("CAPIVARA_AGENT_TASK_NAME", "CapivaraAgent")

SENSITIVE_KEYS = {"pairing_token", "credential_secret", "credential_id", "identity_nonce"}

def _config() -> dict[str, Any]:
    value = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("Agent configuration is invalid")
    return value

def _safe_config(config: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in config.items() if key not in SENSITIVE_KEYS}

def _task_state() -> dict[str, Any]:
    if os.name != "nt":
        return {"state": "portable-test", "task_name": TASK_NAME}
    cp = subprocess.run(
        ["schtasks.exe", "/Query", "/TN", TASK_NAME, "/FO", "LIST", "/V"],
        capture_output=True, text=True, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=10,
    )
    text = (cp.stdout or "") + (cp.stderr or "")
    state = "unknown"
    low = text.lower()
    if "running" in low or "executando" in low:
        state = "running"
    elif "ready" in low or "pronto" in low:
        state = "ready"
    elif cp.returncode != 0:
        state = "missing"
    return {"state": state, "task_name": TASK_NAME, "returncode": cp.returncode}

def _tail(lines: int = 200) -> dict[str, Any]:
    count = max(1, min(int(lines), 5000))
    try:
        data = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        data = []
    return {"path": str(LOG_PATH), "lines": data[-count:]}

def _controller_test(timeout: float = 5.0) -> dict[str, Any]:
    config = _config(); base = str(config.get("controller_url") or "").rstrip("/")
    if not base:
        raise RuntimeError("Controller URL is not configured")
    request = urllib.request.Request(base + "/api/health", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=max(1.0, min(float(timeout), 30.0))) as response:
            return {"reachable": True, "status": response.status, "url": base}
    except Exception as exc:
        return {"reachable": False, "url": base, "error": str(exc)[:1000]}

def _agent_public_network() -> dict[str, Any]:
    config = _config(); base = str(config.get("controller_url") or "").rstrip("/")
    if not base:
        return {"configured": False, "error": "Controller URL is not configured"}
    headers = {
        "Accept": "application/json",
        "X-Capivara-Agent-Credential": str(config.get("credential_id") or ""),
        "X-Capivara-Agent-Secret": str(config.get("credential_secret") or ""),
        "X-Capivara-Agent-Fingerprint": str(config.get("fingerprint") or ""),
    }
    request = urllib.request.Request(base + "/api/agent/public-network", headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
            network = payload.get("public_network") if isinstance(payload, dict) else None
            return network if isinstance(network, dict) else {}
    except Exception as exc:
        return {"configured": False, "error": str(exc)[:1000]}

def snapshot() -> dict[str, Any]:
    config = _config()
    pools = []
    try: pools = pool_inventory(config)
    except Exception: pass
    metrics = metrics_snapshot()
    health = health_inventory(config)
    task = _task_state()
    public_network = _agent_public_network()
    bad = [item for item in health if str(item.get("status") or item.get("health") or "").lower() in {"critical","failed","unhealthy"}]
    overall = "healthy" if task.get("state") in {"running","ready","portable-test"} and not bad else "degraded"
    return {
        "schema_version": 1, "kind": "CapivaraWindowsAgentAdminSnapshot",
        "overall_health": overall, "task": task,
        "agent": {"agent_id": config.get("agent_id"), "node_id": config.get("node_id"), "hostname": socket.gethostname(),
                  "controller_url": config.get("controller_url"), "version": config.get("capivara_version"),
                  "public_network": public_network},
        "config": _safe_config(config), "capabilities": detect_capabilities(), "network": collect_network_inventory(),
        "public_network": public_network,
        "instances": instance_runtime.inventory(config), "instance_health": health,
        "reconciliation": reconciliation_inventory(config), "metrics": metrics, "storage_pools": pools,
        "configuration_state": configuration_state(), "content_state": content_state(), "backup_state": backup_state(),
        "broadcast_state": broadcast_state(), "game_data": game_data_summary(),
    }

def _instance_action(action: str, args: list[str]) -> Any:
    if not args: raise ValueError("instance id is required")
    config = _config(); instance_id = args[0]
    if action == "status": return instance_runtime.status(config, instance_id)
    if action == "doctor": return instance_runtime.doctor(config, instance_id)
    if action in {"start","stop","restart"}: return instance_runtime.lifecycle(config, instance_id, action)
    raise ValueError("unsupported instance action")

def command_catalog() -> list[dict[str, Any]]:
    return [
        {"id":"agent.status","group":"Agent","label":"Status do Agent","command":"agent status"},
        {"id":"agent.health","group":"Agent","label":"Saúde do Agent","command":"agent health"},
        {"id":"agent.info","group":"Agent","label":"Informações","command":"agent info"},
        {"id":"agent.capabilities","group":"Agent","label":"Capabilities","command":"agent capabilities"},
        {"id":"agent.network","group":"Agent","label":"Rede","command":"agent network"},
        {"id":"agent.public-network","group":"Agent","label":"Rede pública","command":"agent public-network"},
        {"id":"agent.controller-test","group":"Agent","label":"Testar Controller","command":"agent controller test"},
        {"id":"agent.logs","group":"Diagnóstico","label":"Logs","command":"agent logs"},
        {"id":"agent.doctor","group":"Diagnóstico","label":"Doctor","command":"agent doctor"},
        {"id":"agent.reconcile","group":"Diagnóstico","label":"Reconciliar instâncias","command":"agent reconcile"},
        {"id":"agent.storage","group":"Storage","label":"Storage Pools","command":"agent storage pools"},
        {"id":"agent.queues","group":"Diagnóstico","label":"Filas","command":"agent queues"},
        {"id":"instance.list","group":"Instâncias","label":"Listar instâncias","command":"instance list"},
        {"id":"instance.status","group":"Instâncias","label":"Status da instância","command":"instance status <id>","requires_instance":True},
        {"id":"instance.doctor","group":"Instâncias","label":"Doctor da instância","command":"instance doctor <id>","requires_instance":True},
        {"id":"instance.start","group":"Instâncias","label":"Iniciar instância","command":"instance start <id>","requires_instance":True,"mutating":True},
        {"id":"instance.stop","group":"Instâncias","label":"Parar instância","command":"instance stop <id>","requires_instance":True,"mutating":True},
        {"id":"instance.restart","group":"Instâncias","label":"Reiniciar instância","command":"instance restart <id>","requires_instance":True,"mutating":True},
    ]

def execute(tokens: list[str]) -> Any:
    if not tokens: return {"catalog": command_catalog()}
    config = _config(); parts = [str(x).strip() for x in tokens if str(x).strip()]
    if parts[:2] == ["agent","status"]: return {"task": _task_state(), "agent_id": config.get("agent_id"), "controller_url": config.get("controller_url")}
    if parts[:2] == ["agent","health"]: return {"overall_health": snapshot()["overall_health"], "instances": health_inventory(config)}
    if parts[:2] == ["agent","info"]: return _safe_config(config)
    if parts[:2] == ["agent","capabilities"]: return detect_capabilities()
    if parts[:2] == ["agent","network"]: return collect_network_inventory()
    if parts[:2] == ["agent","public-network"]: return _agent_public_network()
    if parts[:3] == ["agent","controller","test"]: return _controller_test()
    if parts[:2] == ["agent","logs"]: return _tail(int(parts[2]) if len(parts) > 2 else 200)
    if parts[:2] == ["agent","doctor"]: return {"task": _task_state(), "controller": _controller_test(), "public_network": _agent_public_network(), "health": health_inventory(config), "queues": metrics_snapshot().get("queue_health",{})}
    if parts[:2] == ["agent","reconcile"]: return reconcile_all(config, force=True)
    if parts[:3] == ["agent","storage","pools"]: return pool_inventory(config)
    if parts[:2] == ["agent","queues"]: return metrics_snapshot().get("queue_health",{})
    if parts[:2] == ["instance","list"]: return instance_runtime.inventory(config)
    if len(parts) >= 3 and parts[0] == "instance" and parts[1] in {"status","doctor","start","stop","restart"}:
        return _instance_action(parts[1], parts[2:])
    raise ValueError("unsupported local Agent command")

def main() -> int:
    try:
        if len(sys.argv) < 2 or sys.argv[1] == "snapshot": result = snapshot()
        elif sys.argv[1] == "catalog": result = command_catalog()
        elif sys.argv[1] == "logs": result = _tail(int(sys.argv[2]) if len(sys.argv) > 2 else 200)
        elif sys.argv[1] == "command": result = execute(sys.argv[2:])
        else: raise ValueError("usage: admin_gui_backend.py snapshot|catalog|logs|command ...")
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True, default=str)); return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False)); return 1
if __name__ == "__main__": raise SystemExit(main())
