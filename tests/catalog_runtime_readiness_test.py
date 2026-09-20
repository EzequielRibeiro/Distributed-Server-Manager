#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "catalog_runtime_readiness.py"
spec = importlib.util.spec_from_file_location("catalog_runtime_readiness", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_all_published_runtimes_are_contract_ready() -> None:
    result = module.audit()
    summary = result["summary"]
    published = module.runtime_files()
    published_games = {runtime["game"] for _, runtime in published.values()}
    deferred_count = len(list((ROOT / "catalog" / "v2" / "games").glob("*/deferred/*.json")))
    assert summary["supported_games"] == len(published_games)
    assert summary["published_runtimes"] == len(published)
    assert summary["deferred_runtimes"] == deferred_count
    assert summary["contract_ready_runtimes"] == len(published), result["errors"]
    assert summary["partial_runtimes"] == 0, result["errors"]
    assert result["errors"] == []


def test_static_gate_never_claims_live_binary_e2e() -> None:
    result = module.audit()
    assert result["summary"]["live_binary_e2e_proven"] == 0
    assert all(row["live_binary_e2e"] == "not_proven" for row in result["runtimes"])


def test_runtime_schema_models_current_network_operations() -> None:
    schema = json.loads((ROOT / "catalog" / "v2" / "schemas" / "runtime-definition.schema.json").read_text(encoding="utf-8"))
    operations = schema["$defs"]["network_apply"]["oneOf"]
    by_kind = {op["properties"]["kind"]["const"]: op for op in operations}
    assert set(by_kind) == {"argument", "property", "derived", "reserve"}
    assert {"from", "port"}.issubset(by_kind["derived"]["properties"])
    assert by_kind["derived"]["required"] == ["kind", "from", "port"]
    assert set(by_kind["property"]["properties"]["syntax"]["enum"]) == {"equals", "semicolon", "command"}
    port_schema = schema["$defs"]["network"]["properties"]["ports"]["items"]
    assert set(port_schema["properties"]["exposure"]["enum"]) == {"public", "private", "none"}


def test_minecraft_java_reserved_service_ports_are_declared_and_applied() -> None:
    files = module.runtime_files()
    for runtime_id, (_path, runtime) in sorted(files.items()):
        if runtime.get("game") != "minecraft" or runtime.get("edition") != "java":
            continue
        network = runtime.get("network") or {}
        ports = {str(item.get("name") or ""): item for item in network.get("ports") or []}
        assert set(ports) >= {"game", "rcon", "query", "votifier"}, f"{runtime_id}: missing reserved Minecraft service port"
        assert network.get("block_size") == 4, f"{runtime_id}: Minecraft Java must reserve one four-port block"
        assert ports["query"].get("protocol") == "udp", f"{runtime_id}: query port must be UDP"
        assert ports["votifier"].get("protocol") == "tcp", f"{runtime_id}: Votifier port must be TCP"
        applications = network.get("apply") or []
        properties = {str(item.get("key") or ""): str(item.get("value") or "") for item in applications if item.get("kind") == "property"}
        reserved_only = {str(item.get("port") or "") for item in applications if item.get("kind") == "reserve"}
        assert properties.get("enable-rcon") == "true", f"{runtime_id}: RCON must be enabled explicitly"
        assert properties.get("rcon.port") == "{rcon}", f"{runtime_id}: RCON port must use reserved role"
        assert properties.get("query.port") == "{query}", f"{runtime_id}: query port must use reserved role"
        assert "votifier" in reserved_only, f"{runtime_id}: Votifier port must remain reserved even without a plugin config target"


def test_every_published_runtime_validates_against_canonical_schema() -> None:
    schema = json.loads((ROOT / "catalog" / "v2" / "schemas" / "runtime-definition.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    published = {row["id"] for row in module.audit()["runtimes"]}
    files = module.runtime_files()
    for runtime_id in sorted(published):
        _, runtime = files[runtime_id]
        errors = sorted(validator.iter_errors(runtime), key=lambda item: list(item.absolute_path))
        assert not errors, f"{runtime_id}: " + "; ".join(error.message for error in errors)


if __name__ == "__main__":
    test_all_published_runtimes_are_contract_ready()
    test_static_gate_never_claims_live_binary_e2e()
    test_runtime_schema_models_current_network_operations()
    test_every_published_runtime_validates_against_canonical_schema()
    print("catalog runtime readiness: OK")
