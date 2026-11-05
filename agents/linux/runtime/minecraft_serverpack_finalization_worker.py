#!/usr/bin/env python3
"""One-shot finalization worker; fully revalidate identity and state under lock.

This script is intentionally separate from agent.py and never imports it.
Exit does not imply success: durable journals are authoritative.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

from minecraft_serverpack_finalization_scheduler import scan_pending_finalizations
from runtime_lock import instance_lock
from runtime_operations import read_operation


def execute_one(config_path: Path, instance_id: str) -> list[dict[str, str]]:
    if not instance_id or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-" for c in instance_id):
        raise ValueError("invalid instance")
    # No recovery permitted without a fresh explicit policy check.
    allowed = os.environ.get("CAPIVARA_SERVERPACK_FINALIZATION_RECONCILE_INSTANCE", "")
    recover = (os.environ.get("CAPIVARA_SERVERPACK_FINALIZATION_RECOVER") == "1"
               and os.environ.get("CAPIVARA_SERVERPACK_FINALIZATION_RECOVER_ACK") == "AUTHORIZED")
    reconcile = os.environ.get("CAPIVARA_SERVERPACK_FINALIZATION_RECONCILE") == "1"
    if allowed != instance_id or not (recover or reconcile):
        raise PermissionError("reconciliation is not authorized")
    if not config_path.is_absolute() or config_path.is_symlink():
        raise ValueError("invalid Agent config path")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    agent_id = str(config.get("agent_id") or "")
    if not agent_id:
        raise ValueError("Agent identity missing")
    # Import operational dependencies ONLY in the child, so packages with an
    # older updater layout still boot agent.py and send heartbeat.
    from minecraft_serverpack_finalization_dispatcher import dispatch_published_completion
    if recover:
        from minecraft_serverpack_finalization_operational import (
            recover_pending_operational, recovery_feature_allowed,
        )
        recover = recovery_feature_allowed(instance_id, agent_id)
    if not recover and not reconcile:
        raise PermissionError("Server Pack migration policy declined recovery")

    def apply(outer, result):
        if outer.get("instance_id") != instance_id or result.get("instance_id") != instance_id:
            return False
        if result.get("status") == "completed" and (reconcile or recover):
            dispatch_published_completion(
                outer, result, agent_id=agent_id, allowed_instance_id=instance_id)
            return True
        if result.get("status") == "running" and recover:
            recover_pending_operational(
                config=config, operation=outer, provisioning=result,
                allowed_instance_id=instance_id)
            return True
        return False

    # A child that crashes does not release a completed barrier; retry re-reads
    # the durable journals. The instance lock prevents concurrent workers.
    state_dir = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
    if not state_dir.is_absolute():
        raise ValueError("invalid Agent state directory")
    results = scan_pending_finalizations(
        state_root=state_dir, agent_id=agent_id,
        lock_instance=lambda iid: instance_lock(
            iid, "minecraft_serverpack_finalization_worker", timeout_seconds=0.25),
        read_operation=read_operation, dispatch=apply, enabled=True,
        max_candidates=4,
    )
    return [x for x in results if x.get("instance_id") == instance_id]


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(2)
    try:
        outcome = execute_one(Path(sys.argv[1]), sys.argv[2])
        print(json.dumps({"status": "completed", "observations": outcome}), flush=True)
    except Exception as exc:
        # Avoid exposing credentials or untrusted paths in the worker log.
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}), flush=True)
        raise SystemExit(1)
