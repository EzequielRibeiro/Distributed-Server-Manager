#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "tools" / "catalog_external_query_compatibility.py"
spec = importlib.util.spec_from_file_location("catalog_external_query_compatibility", MODULE)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_every_published_runtime_has_external_query_mapping() -> None:
    result = module.audit()
    assert result["errors"] == [], result["errors"]
    summary = result["summary"]
    assert summary["mapped_games"] == summary["published_games"]
    assert summary["mapped_runtimes"] == summary["published_runtimes"]


def test_dayz_matches_linuxgsm_and_gamedig_port_topology() -> None:
    runtimes = module._runtime_files()
    runtime = runtimes["dayz.stable"]
    ports = {item["name"]: item for item in runtime["network"]["ports"]}
    assert ports["game"]["offset"] == 0
    assert ports["game_aux"]["offset"] == 2
    assert ports["battleye"]["offset"] == 4
    assert ports["steam_query"]["offset"] == 24714

    manifest = module._load(module.COMPAT)
    profile = manifest["games"]["dayz"]
    assert profile["gamedig_type"] == "dayz"
    assert profile["checker_type"] == "valve"
    assert profile["query_role"] == "steam_query"
    assert profile["offset"] == 24714


if __name__ == "__main__":
    test_every_published_runtime_has_external_query_mapping()
    test_dayz_matches_linuxgsm_and_gamedig_port_topology()
    print("external query compatibility: OK")
