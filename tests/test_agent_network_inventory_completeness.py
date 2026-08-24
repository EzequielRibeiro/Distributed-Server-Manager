#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, relative_path: str):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("module_name", "relative_path", "source"),
    [
        ("linux_network_inventory", "agents/linux/runtime/network_inventory.py", "ss"),
        ("windows_network_inventory", "agents/windows/runtime/network_inventory.py", "netstat"),
    ],
)
def test_inventory_marks_successful_empty_collection_complete(
    monkeypatch,
    module_name,
    relative_path,
    source,
):
    module = _load_module(module_name, relative_path)

    def successful(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(module.subprocess, "run", successful)

    inventory = module.collect_network_inventory()

    assert inventory["source"] == source
    assert inventory["tcp_listen"] == []
    assert inventory["udp_listen"] == []
    assert inventory["tcp_complete"] is True
    assert inventory["udp_complete"] is True
    assert inventory["complete"] is True


@pytest.mark.parametrize(
    ("module_name", "relative_path", "source"),
    [
        ("linux_network_inventory_error", "agents/linux/runtime/network_inventory.py", "ss"),
        ("windows_network_inventory_error", "agents/windows/runtime/network_inventory.py", "netstat"),
    ],
)
def test_inventory_marks_collection_failure_incomplete(
    monkeypatch,
    module_name,
    relative_path,
    source,
):
    module = _load_module(module_name, relative_path)

    def failing(*args, **kwargs):
        raise OSError("collector unavailable")

    monkeypatch.setattr(module.subprocess, "run", failing)

    inventory = module.collect_network_inventory()

    assert inventory["source"] == source
    assert inventory["tcp_listen"] == []
    assert inventory["udp_listen"] == []
    assert inventory["tcp_complete"] is False
    assert inventory["udp_complete"] is False
    assert inventory["complete"] is False
