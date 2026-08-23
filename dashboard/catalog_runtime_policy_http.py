#!/usr/bin/env python3
"""HTTP boundary for Catalog runtime/startup policies."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from catalog_runtime_policy import load_policy, save_policy

RUNTIME_POLICY_PATH = "/api/catalog/runtime-policy"


def _role(user: dict[str, Any] | None) -> str:
    return str((user or {}).get("role") or "").strip().lower()


def _runtime(root: Path, runtime_id: str) -> dict[str, Any]:
    runtime_id = str(runtime_id or "").strip()
    runtimes = root / "catalog" / "v2" / "games"
    for path in runtimes.glob("*/runtimes/*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict) and str(payload.get("id") or "") == runtime_id:
            return payload
    raise ValueError("runtime not found")


def dispatch_catalog_runtime_policy_get(path: str, query_string: str, *, user, root: Path):
    if path != RUNTIME_POLICY_PATH:
        return None
    if _role(user) not in {"admin", "controller", "operator"}:
        return 403, {"error": "forbidden", "message": "catalog administration access required"}
    query = parse_qs(query_string, keep_blank_values=True)
    runtime_id = (query.get("runtime_id") or [""])[0]
    try:
        runtime = _runtime(root, runtime_id)
        return 200, {"policy": load_policy(root, runtime), "runtime": runtime, "can_edit": _role(user) == "admin"}
    except ValueError as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}
    except Exception:
        return 500, {"error": "runtime_policy_failed", "message": "Não foi possível carregar os parâmetros do runtime."}


def dispatch_catalog_runtime_policy_put(path: str, payload: Any, *, user, root: Path):
    if path != RUNTIME_POLICY_PATH:
        return None
    if _role(user) != "admin":
        return 403, {"error": "forbidden", "message": "admin access required"}
    if not isinstance(payload, dict):
        return 400, {"error": "invalid_request", "message": "payload must be an object"}
    runtime_id = str(payload.get("runtime_id") or "").strip()
    try:
        _runtime(root, runtime_id)
        policy = payload.get("policy") if isinstance(payload.get("policy"), dict) else payload
        return 200, {"policy": save_policy(root, runtime_id, policy), "can_edit": True}
    except ValueError as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}
    except Exception:
        return 500, {"error": "runtime_policy_failed", "message": "Não foi possível salvar os parâmetros do runtime."}


__all__ = ["RUNTIME_POLICY_PATH", "dispatch_catalog_runtime_policy_get", "dispatch_catalog_runtime_policy_put"]
