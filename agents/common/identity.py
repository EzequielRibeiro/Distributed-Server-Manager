#!/usr/bin/env python3
"""Local identity helpers shared by Agent platforms."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import socket
import uuid
from pathlib import Path
from typing import Any


def _machine_id() -> str:
    for candidate in (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id")):
        try:
            value = candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return str(uuid.getnode())


def generate_local_identity() -> dict[str, Any]:
    """Generate stable opaque identifiers and a machine-bound fingerprint seed."""
    hostname = socket.gethostname() or "capivara-agent"
    nonce = secrets.token_hex(32)
    material = f"{_machine_id()}\0{hostname}\0{nonce}".encode("utf-8")
    fingerprint = hashlib.sha256(material).hexdigest()
    suffix = fingerprint[:20]
    return {
        "agent_id": f"agent-{suffix}",
        "node_id": f"node-{suffix}",
        "hostname": hostname,
        "fingerprint": f"sha256:{fingerprint}",
        "identity_nonce": nonce,
    }


def write_identity(path: Path, identity: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(identity, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    os.chmod(path, 0o600)
