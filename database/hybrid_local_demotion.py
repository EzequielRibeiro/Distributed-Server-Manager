#!/usr/bin/env python3
"""Reconcile local files after Hybrid -> Controller demotion."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Any


class HybridLocalDemotionError(RuntimeError):
    """Raised when local Agent state cannot be removed safely."""


def _render_shell_value(value: str) -> str:
    if "\n" in value or "\r" in value or '"' in value:
        raise HybridLocalDemotionError("unsafe value for agent.conf")
    return value.replace("\\", "\\\\")


def _set_shell_value(text: str, key: str, value: str) -> str:
    rendered = f'{key}="{_render_shell_value(value)}"'
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(rendered, text)
    if text and not text.endswith("\n"):
        text += "\n"
    return text + rendered + "\n"


def reconcile_local_controller_config(root: Path, *, node_id: str) -> dict[str, Any]:
    """Remove local Agent identity from agent.conf without touching secrets.

    The file is retained because Controller installations may later be promoted
    again. Ownership and mode are preserved exactly as in Hybrid promotion.
    """
    config = Path(root) / "config" / "agent.conf"
    if not config.is_file():
        return {"config_path": str(config), "config_changed": False, "config_missing": True}

    metadata = config.stat()
    original = config.read_text(encoding="utf-8")
    updated = original
    for key, value in (
        ("AGENT_ID", ""),
        ("AGENT_NAME", ""),
        ("AGENT_STATUS", "inactive"),
        ("DSM_NODE_ID", node_id),
        ("DSM_NODE_ROLE", "controller"),
    ):
        updated = _set_shell_value(updated, key, value)

    changed = updated != original
    if changed:
        fd, temporary_name = tempfile.mkstemp(prefix=f".{config.name}.", dir=str(config.parent))
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(updated)
                handle.flush()
                os.fsync(handle.fileno())
            os.chown(temporary, metadata.st_uid, metadata.st_gid)
            os.chmod(temporary, metadata.st_mode & 0o777)
            os.replace(temporary, config)
        finally:
            if temporary.exists():
                temporary.unlink()

    return {"config_path": str(config), "config_changed": changed, "config_missing": False}


__all__ = ["HybridLocalDemotionError", "reconcile_local_controller_config"]
