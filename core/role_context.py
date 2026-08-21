#!/usr/bin/env python3
"""Read-only local role resolution for Capivara CLI dispatch.

This module deliberately avoids importing database/runtime backends.  It reads
only explicit environment/configuration state and fails closed when a role
cannot be determined.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Mapping

VALID_ROLES = {"controller", "agent", "hybrid"}


def _normalize(value: object) -> str | None:
    role = str(value or "").strip().lower()
    return role if role in VALID_ROLES else None


def _shell_value(path: Path, key: str) -> str | None:
    """Read one simple KEY=value assignment without sourcing shell code."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=\s*(.*?)\s*$")
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = pattern.match(raw)
        if not match:
            continue
        value = match.group(1).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'\"', "'"}:
            value = value[1:-1]
        elif "#" in value:
            value = value.split("#", 1)[0].strip()
        return value.strip()
    return None


def resolve_local_role(
    root: Path | str,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Resolve role using only local, observational inputs.

    Precedence:
      1. CAPIVARA_NODE_ROLE / DSM_NODE_ROLE environment override;
      2. DSM_NODE_ROLE persisted in config/dsm.conf;
      3. standalone Linux Agent config presence;
      4. legacy monolithic Agent identity only when unambiguous enough to
         identify an Agent capability, otherwise return unknown.
    """
    env = os.environ if environ is None else environ
    root_path = Path(root).resolve()

    for key in ("CAPIVARA_NODE_ROLE", "DSM_NODE_ROLE"):
        role = _normalize(env.get(key))
        if role:
            return {"role": role, "source": f"env:{key}", "root": str(root_path)}

    dsm_conf = root_path / "config" / "dsm.conf"
    persisted = _normalize(_shell_value(dsm_conf, "DSM_NODE_ROLE"))
    if persisted:
        return {"role": persisted, "source": "config:dsm.conf", "root": str(root_path)}

    standalone_config = Path(
        env.get("CAPIVARA_AGENT_CONFIG", "/etc/capivara-agent/agent.json")
    )
    try:
        payload = json.loads(standalone_config.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = None
    if isinstance(payload, dict) and str(payload.get("agent_id") or "").strip():
        return {
            "role": "agent",
            "source": "config:standalone-agent",
            "root": str(root_path),
        }

    # Older monolithic installs predate persisted DSM_NODE_ROLE.  A populated
    # agent.conf proves Agent capability but does not distinguish Agent from
    # Hybrid safely, so fail closed rather than inventing a role.
    agent_id = _shell_value(root_path / "config" / "agent.conf", "AGENT_ID")
    if str(agent_id or "").strip():
        return {
            "role": "unknown",
            "source": "legacy:agent-identity-ambiguous",
            "root": str(root_path),
            "hint": "persist DSM_NODE_ROLE=agent|hybrid in config/dsm.conf",
        }

    return {
        "role": "unknown",
        "source": "unresolved",
        "root": str(root_path),
        "hint": "persist DSM_NODE_ROLE=controller|agent|hybrid in config/dsm.conf",
    }


def allows(role: str, allowed: set[str] | frozenset[str]) -> bool:
    return role in allowed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only Capivara local role resolver")
    parser.add_argument("--root", default=os.environ.get("DSM_ROOT", "/opt/dsm"))
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = resolve_local_role(Path(args.root))
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(payload["role"])
    return 0 if payload["role"] in VALID_ROLES else 1


if __name__ == "__main__":
    raise SystemExit(main())
