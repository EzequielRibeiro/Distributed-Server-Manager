#!/usr/bin/env python3
"""Periodic, game-neutral server update inventory for the Linux Agent."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import game_data_state
import provisioning_state
from server_update_provider import detect_update

STATE_DIR = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
INVENTORY_PATH = STATE_DIR / "server-update-inventory.json"
DEFAULT_INTERVAL_SECONDS = 300
_LAST_REFRESH_MONOTONIC = 0.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read() -> dict[str, Any]:
    try:
        value = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema_version": 1, "kind": "ServerUpdateInventory", "checked_at": None, "games": []}
    return value if isinstance(value, dict) else {"schema_version": 1, "kind": "ServerUpdateInventory", "checked_at": None, "games": []}


def _write(payload: dict[str, Any]) -> None:
    INVENTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = INVENTORY_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    temp.replace(INVENTORY_PATH)
    os.chmod(INVENTORY_PATH, 0o600)


def _interval(config: dict[str, Any]) -> int:
    try:
        value = int(config.get("server_update_check_interval_seconds", DEFAULT_INTERVAL_SECONDS))
    except (TypeError, ValueError):
        value = DEFAULT_INTERVAL_SECONDS
    return max(60, min(value, 86400))


def _historical_selection(game: str) -> dict[str, Any] | None:
    """Recover the latest Controller-resolved selection for already-provisioned data."""
    root = Path(provisioning_state.HISTORY_ROOT)
    try:
        paths = sorted(root.glob("*.request.json"), key=lambda path: path.stat().st_mtime_ns, reverse=True)
    except OSError:
        return None
    for path in paths:
        payload = provisioning_state.read_json(path)
        if not isinstance(payload, dict):
            continue
        content = payload.get("content") if isinstance(payload.get("content"), dict) else {}
        selection = content.get("selection") if isinstance(content.get("selection"), dict) else None
        if selection and str(selection.get("game") or "").strip() == game:
            return dict(selection)
    return None


def refresh(config: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    """Refresh remote-version state without applying any update."""
    global _LAST_REFRESH_MONOTONIC
    now_mono = time.monotonic()
    if not force and _LAST_REFRESH_MONOTONIC and now_mono - _LAST_REFRESH_MONOTONIC < _interval(config):
        return _read()

    items: list[dict[str, Any]] = []
    for state in game_data_state.list_game_data():
        game = str(state.get("game") or "").strip()
        target = str(state.get("target_path") or "").strip()
        selection = state.get("update_selection") if isinstance(state.get("update_selection"), dict) else None
        if not game or not target:
            continue
        if not selection:
            selection = _historical_selection(game)
        if not selection:
            items.append({
                "game": game,
                "provider": state.get("provider"),
                "state": "metadata_unavailable",
                "detector_supported": False,
                "checked_at": _now(),
            })
            continue
        try:
            provider = str(selection.get("provider") or "").strip().lower()
            steamcmd = None
            if provider == "steam":
                from game_data_executor import _steamcmd
                steamcmd = _steamcmd()
            detail = detect_update(selection, Path(target), steamcmd)
            items.append({"game": game, "checked_at": _now(), **detail})
        except Exception as exc:
            items.append({
                "game": game,
                "provider": selection.get("provider"),
                "state": "probe_failed",
                "detector_supported": True,
                "error": str(exc)[:2000],
                "checked_at": _now(),
            })

    payload = {
        "schema_version": 1,
        "kind": "ServerUpdateInventory",
        "checked_at": _now(),
        "interval_seconds": _interval(config),
        "games": items,
    }
    _write(payload)
    _LAST_REFRESH_MONOTONIC = now_mono
    return payload


def inventory() -> dict[str, Any]:
    return _read()


def for_game(game: str) -> dict[str, Any] | None:
    token = str(game or "").strip()
    if not token:
        return None
    for item in _read().get("games", []):
        if isinstance(item, dict) and str(item.get("game") or "") == token:
            return dict(item)
    return None


__all__ = ["DEFAULT_INTERVAL_SECONDS", "for_game", "inventory", "refresh"]
