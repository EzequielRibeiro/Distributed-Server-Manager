#!/usr/bin/env python3
"""Bounded, failure-isolated batch orchestration for Dashboard SSH installs."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from agent_installation_api import create_agent_installation_for_user

MAX_BATCH_TARGETS = 500
MAX_BATCH_CONCURRENCY = 20


def create_agent_installation_batch_for_user(
    user: dict[str, Any] | None,
    backend,
    payload: dict[str, Any] | None,
    *,
    ssh_runner=None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    targets = payload.get("targets")
    if not isinstance(targets, list) or not targets:
        raise ValueError("targets must be a non-empty array")
    if len(targets) > MAX_BATCH_TARGETS:
        raise ValueError(f"batch exceeds maximum of {MAX_BATCH_TARGETS} targets")
    try:
        concurrency = int(payload.get("concurrency", 5) or 5)
    except (TypeError, ValueError) as exc:
        raise ValueError("concurrency must be an integer") from exc
    if not 1 <= concurrency <= MAX_BATCH_CONCURRENCY:
        raise ValueError(f"concurrency must be between 1 and {MAX_BATCH_CONCURRENCY}")

    common = {k: v for k, v in payload.items() if k not in {"targets", "concurrency"}}
    common["method"] = "ssh"
    results: list[dict[str, Any] | None] = [None] * len(targets)

    def run(index: int, target: Any):
        if not isinstance(target, dict):
            return index, {"ok": False, "status": "invalid", "error": "target must be an object"}
        merged = dict(common)
        merged.update(target)
        merged["method"] = "ssh"
        if "name" in merged and "agent_name" not in merged:
            merged["agent_name"] = merged["name"]
        if "host" in merged and "ssh_host" not in merged:
            merged["ssh_host"] = merged["host"]
        if "user" in merged and "ssh_user" not in merged:
            merged["ssh_user"] = merged["user"]
        if "port" in merged and "ssh_port" not in merged:
            merged["ssh_port"] = merged["port"]
        try:
            result = create_agent_installation_for_user(user, backend, merged, ssh_runner=ssh_runner)
            return index, {
                "ok": True,
                "status": "bootstrap_completed",
                "name": str(merged.get("agent_name", "") or "").strip() or None,
                "host": str(merged.get("ssh_host", "") or ""),
                **result,
            }
        except Exception as exc:
            return index, {
                "ok": False,
                "status": "failed",
                "name": str(merged.get("agent_name", "") or "").strip() or None,
                "host": str(merged.get("ssh_host", "") or ""),
                "error": str(exc),
            }

    workers = min(concurrency, len(targets))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="dashboard-agent-deploy") as executor:
        futures = [executor.submit(run, index, target) for index, target in enumerate(targets)]
        for future in as_completed(futures):
            index, result = future.result()
            results[index] = result

    succeeded = sum(1 for result in results if result and result.get("ok"))
    return {
        "ok": succeeded == len(results),
        "state": "completed" if succeeded == len(results) else "partial",
        "total": len(results),
        "succeeded": succeeded,
        "failed": len(results) - succeeded,
        "targets": results,
    }
