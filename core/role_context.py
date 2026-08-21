#!/usr/bin/env python3
"""Read-only local role resolution for Capivara CLI dispatch.

The resolver never initializes repositories, applies migrations, refreshes
health, or writes configuration. It consumes explicit local state and uses a
strictly read-only SQLite fallback only for older monolithic installs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sqlite3
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


def _sqlite_role(root: Path, dsm_conf: Path) -> str | None:
    driver = str(_shell_value(dsm_conf, "DSM_DATABASE_DRIVER") or "sqlite").lower()
    if driver not in {"sqlite", "sqlite3"}:
        return None
    configured = str(_shell_value(dsm_conf, "DSM_DATABASE") or "").strip()
    database = Path(configured) if configured else root / "data" / "capivara.db"
    if not database.is_absolute():
        database = root / database
    try:
        connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True, timeout=1)
    except sqlite3.Error:
        return None
    try:
        connection.row_factory = sqlite3.Row
        hostname = socket.gethostname()
        for column in ("id", "name"):
            try:
                row = connection.execute(
                    f"SELECT role FROM nodes WHERE {column}=? LIMIT 1", (hostname,)
                ).fetchone()
            except sqlite3.Error:
                row = None
            if row is not None:
                role = _normalize(row["role"])
                if role:
                    return role
        try:
            rows = connection.execute("SELECT role FROM nodes LIMIT 2").fetchall()
        except sqlite3.Error:
            rows = []
        return _normalize(rows[0]["role"]) if len(rows) == 1 else None
    finally:
        connection.close()


def resolve_local_role(
    root: Path | str,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Resolve role from local observational inputs, highest confidence first."""
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

    # install.sh already persists DSM_NODE_ROLE in agent.conf for all three
    # monolithic profiles. Controller -> Hybrid reconciliation also updates it.
    agent_conf = root_path / "config" / "agent.conf"
    persisted = _normalize(_shell_value(agent_conf, "DSM_NODE_ROLE"))
    if persisted:
        return {"role": persisted, "source": "config:agent.conf", "root": str(root_path)}

    standalone_config = Path(
        env.get("CAPIVARA_AGENT_CONFIG", "/etc/capivara-agent/agent.json")
    )
    try:
        payload = json.loads(standalone_config.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = None
    if isinstance(payload, dict) and str(payload.get("agent_id") or "").strip():
        return {"role": "agent", "source": "config:standalone-agent", "root": str(root_path)}

    legacy_role = _sqlite_role(root_path, dsm_conf)
    if legacy_role:
        return {"role": legacy_role, "source": "legacy:sqlite-readonly", "root": str(root_path)}

    agent_id = _shell_value(agent_conf, "AGENT_ID")
    source = "legacy:agent-identity-ambiguous" if str(agent_id or "").strip() else "unresolved"
    return {
        "role": "unknown",
        "source": source,
        "root": str(root_path),
        "hint": "persist DSM_NODE_ROLE=controller|agent|hybrid in config/agent.conf or config/dsm.conf",
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
