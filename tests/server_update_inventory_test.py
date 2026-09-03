#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
sys.path.insert(0, str(RUNTIME))

import server_update_inventory as inventory


def test_refresh_is_game_neutral_and_cached() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        inventory.INVENTORY_PATH = root / "server-update-inventory.json"
        inventory._LAST_REFRESH_MONOTONIC = 0.0
        selection = {"provider": "steam", "game": "example", "install": {"package_id": "123"}}
        state = {"game": "example", "provider": "steam", "target_path": str(root / "game"), "update_selection": selection}
        calls = []

        def fake_detect(received, target, steamcmd):
            calls.append((received, target, steamcmd))
            return {"schema_version": 1, "provider": "steam", "detector_supported": True,
                    "installed_version": "10", "available_version": "11", "state": "update_available",
                    "rollback_supported": False}

        with mock.patch.object(inventory.game_data_state, "list_game_data", return_value=[state]), \
             mock.patch("game_data_executor._steamcmd", return_value="/tmp/steamcmd"), \
             mock.patch.object(inventory, "detect_update", side_effect=fake_detect):
            first = inventory.refresh({"server_update_check_interval_seconds": 300}, force=True)
            second = inventory.refresh({"server_update_check_interval_seconds": 300})

        assert first["games"][0]["state"] == "update_available"
        assert second["games"][0]["available_version"] == "11"
        assert len(calls) == 1


def test_historical_selection_recovery() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        history = root / "history"
        history.mkdir()
        payload = {"content": {"selection": {"provider": "steam", "game": "example", "install": {"package_id": "456"}}}}
        (history / "job.request.json").write_text(json.dumps(payload), encoding="utf-8")
        with mock.patch.object(inventory.provisioning_state, "HISTORY_ROOT", history):
            selection = inventory._historical_selection("example")
        assert selection is not None
        assert selection["install"]["package_id"] == "456"


def test_runtime_metrics_publishes_server_update_inventory() -> None:
    text = (RUNTIME / "runtime_metrics.py").read_text(encoding="utf-8")
    assert 'payload["server_updates"] = refresh_server_updates(config)' in text
    monitor = (RUNTIME / "server_update_inventory.py").read_text(encoding="utf-8").lower()
    for game_name in ("dayz", "zomboid", "arma", "rust", "palworld"):
        assert game_name not in monitor


if __name__ == "__main__":
    test_refresh_is_game_neutral_and_cached()
    test_historical_selection_recovery()
    test_runtime_metrics_publishes_server_update_inventory()
    print("server update inventory: OK")
