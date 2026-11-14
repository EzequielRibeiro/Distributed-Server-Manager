#!/usr/bin/env python3
"""Customer-safe, controller-scoped selector for individual eligible servers.

Public references are opaque locators, never authorization credentials. Resolve
them exclusively against active candidates belonging to the customer's
Controller, then re-run normal placement eligibility at creation time.
"""
from __future__ import annotations

import hashlib
import re
import secrets
from typing import Any, Iterable

_PUBLIC_REF_PATTERN = re.compile(r"^srv-[a-f0-9]{24}$")


def public_server_ref(controller_id: str, agent_id: str) -> str:
    """Stable public locator without exposing Agent/Node IDs or addresses."""
    key = f"capivara:public-server:v1|{controller_id}|{agent_id}"
    return "srv-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def resolve_server_ref(
    controller_id: str,
    selection_ref: str,
    candidates: Iterable[dict[str, Any]],
    *,
    region_id: str | None = None,
) -> str:
    """Return an authorized candidate's internal Agent ID or fail closed."""
    ref = str(selection_ref or "").strip()
    if not _PUBLIC_REF_PATTERN.fullmatch(ref):
        raise ValueError("Servidor selecionado indisponível.")
    for candidate in candidates:
        agent_id = str(candidate.get("agent_id") or "")
        candidate_region = str(candidate.get("region_id") or "")
        if not agent_id or (region_id and candidate_region != region_id):
            continue
        if secrets.compare_digest(public_server_ref(controller_id, agent_id), ref):
            return agent_id
    raise ValueError("Servidor selecionado indisponível.")


__all__ = ["public_server_ref", "resolve_server_ref"]
