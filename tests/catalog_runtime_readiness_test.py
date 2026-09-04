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
    assert summary["supported_games"] == 16
    assert summary["published_runtimes"] == 27
    assert summary["deferred_runtimes"] == 4
    assert summary["contract_ready_runtimes"] == 27, result["errors"]
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
    assert set(by_kind) == {"argument", "property", "derived"}
    assert {"from", "port"}.issubset(by_kind["derived"]["properties"])
    assert by_kind["derived"]["required"] == ["kind", "from", "port"]
    assert set(by_kind["property"]["properties"]["syntax"]["enum"]) == {"equals", "semicolon"}


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
