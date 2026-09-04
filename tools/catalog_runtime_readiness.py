#!/usr/bin/env python3
"""Static readiness audit for every runtime published by Catalog v2.

This gate deliberately distinguishes a contract-ready runtime from a live-binary
E2E proof. It validates what the repository can prove deterministically:
Catalog/support-matrix parity, provider/version contracts, OS coverage, process
shape, network allocation/application semantics, and safe placeholder usage.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog" / "v2"
MATRIX = CATALOG / "support-matrix.json"
GAMES = CATALOG / "games"

PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
PORT_PLACEHOLDERS = {
    "game_port": "game", "query_port": "query", "steam_port": "steam",
    "rcon_port": "rcon", "battleye_port": "battleye",
}
GENERIC_PLACEHOLDERS = {
    "config_file", "profiles_dir", "instance_dir", "server_name", "max_players",
    "map", "world", "save", "password", "admin_password", "memory_mb",
    "steam_game_server_login_token", "eos_client_id", "eos_client_secret",
}
ALLOWED_PROVIDERS = {"steam", "http", "http-archive", "github", "local", "custom", "source-build"}
EXECUTABLE_PROVIDERS = {"steam", "http", "http-archive", "github", "source-build"}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected JSON object")
    return value


def runtime_files() -> dict[str, tuple[Path, dict[str, Any]]]:
    result: dict[str, tuple[Path, dict[str, Any]]] = {}
    for path in sorted(GAMES.glob("*/runtimes/*.json")):
        runtime = load(path)
        rid = str(runtime.get("id") or "")
        if not rid:
            continue
        if rid in result:
            raise ValueError(f"duplicate runtime id: {rid}")
        result[rid] = (path, runtime)
    return result


def _args(runtime: dict[str, Any]) -> list[str]:
    raw = (runtime.get("process") or {}).get("args")
    if raw is None:
        return []
    return [raw] if isinstance(raw, str) else [str(item) for item in raw]


def _network_findings(runtime: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    network = runtime.get("network")
    if not network:
        return findings
    ports = network.get("ports") or []
    names: set[str] = set()
    offsets: dict[str, int] = {}
    occupied: set[tuple[int, str]] = set()
    block_size = int(network.get("block_size") or 0)
    if network.get("allocation") != "block" or block_size < 1:
        findings.append("invalid network allocation/block_size")
    for item in ports:
        name = str(item.get("name") or "")
        proto = str(item.get("protocol") or "")
        offset = item.get("offset")
        if not name or name in names:
            findings.append(f"invalid/duplicate port name: {name!r}")
        names.add(name)
        if proto not in {"tcp", "udp"}:
            findings.append(f"invalid protocol for {name}: {proto!r}")
        if not isinstance(offset, int) or offset < 0 or offset >= block_size:
            findings.append(f"port {name} offset {offset!r} outside allocated block")
        else:
            offsets[name] = offset
            if (offset, proto) in occupied:
                findings.append(f"duplicate {proto} offset {offset}")
            occupied.add((offset, proto))
    for op in network.get("apply") or []:
        kind = op.get("kind")
        if kind == "argument":
            if not str(op.get("template") or ""):
                findings.append("network argument operation missing template")
        elif kind == "property":
            if not all(str(op.get(k) or "") for k in ("file", "key")) or "value" not in op:
                findings.append("network property operation incomplete")
            if op.get("syntax") not in {None, "equals", "semicolon"}:
                findings.append(f"unsupported network property syntax: {op.get('syntax')!r}")
        elif kind == "derived":
            source = str(op.get("from") or "")
            target = str(op.get("port") or "")
            if source not in names:
                findings.append(f"derived network source not declared: {source}")
            if target not in names:
                findings.append(f"derived network target not declared: {target}")
            if source in offsets and target in offsets and offsets[source] == offsets[target]:
                findings.append(f"derived network target {target} does not differ from source {source}")
        else:
            findings.append(f"unsupported network apply kind: {kind!r}")
    return findings


def _placeholder_findings(runtime: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    names = {str(p.get("name") or "") for p in ((runtime.get("network") or {}).get("ports") or [])}
    text = "\n".join([str((runtime.get("process") or {}).get("executable") or ""), *_args(runtime)])
    for token in sorted(set(PLACEHOLDER.findall(text))):
        role = PORT_PLACEHOLDERS.get(token)
        if role and role not in names:
            findings.append(f"placeholder {{{token}}} has no declared {role} port")
        elif not role and token not in GENERIC_PLACEHOLDERS:
            findings.append(f"unclassified runtime placeholder: {{{token}}}")
    return findings


def audit() -> dict[str, Any]:
    matrix = load(MATRIX)
    files = runtime_files()
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    games: dict[str, dict[str, int]] = {}
    published = matrix.get("published_runtimes") or []
    for entry in published:
        rid = str(entry.get("id") or "")
        game = str(entry.get("game") or "")
        row: dict[str, Any] = {
            "id": rid, "game": game, "catalog_status": "supported",
            "catalog_contract": "failed", "agent_contract": "unknown",
            "live_binary_e2e": "not_proven", "findings": [],
        }
        located = files.get(rid)
        if not located:
            row["findings"].append("published runtime definition missing")
        else:
            path, runtime = located
            row["path"] = path.relative_to(ROOT).as_posix()
            if runtime.get("schema_version") != 2 or runtime.get("kind") != "RuntimeDefinition":
                row["findings"].append("runtime schema identity is not v2 RuntimeDefinition")
            for key in ("id", "game"):
                if str(runtime.get(key) or "") != str(entry.get(key) or ""):
                    row["findings"].append(f"support-matrix/runtime {key} mismatch")
            requirements = runtime.get("requirements") or {}
            ros = sorted(str(v) for v in requirements.get("os") or [])
            mos = sorted(str(v) for v in entry.get("os") or [])
            if ros != mos:
                row["findings"].append(f"OS mismatch runtime={ros} matrix={mos}")
            process = runtime.get("process") or {}
            if process.get("engine") != entry.get("engine"):
                row["findings"].append("engine mismatch")
            if not str(process.get("executable") or ""):
                row["findings"].append("process executable missing")
            artifact = runtime.get("artifact") or {}
            provider = str(artifact.get("provider") or "")
            if provider != entry.get("provider"):
                row["findings"].append("provider mismatch")
            if provider not in ALLOWED_PROVIDERS:
                row["findings"].append(f"unknown provider: {provider}")
            if provider not in EXECUTABLE_PROVIDERS:
                row["findings"].append(f"provider has no canonical Agent execution contract: {provider}")
            version = runtime.get("version") or {}
            if version.get("strategy") != entry.get("version_strategy"):
                row["findings"].append("version strategy mismatch")
            if version.get("strategy") == "dynamic" and not version.get("resolver"):
                row["findings"].append("dynamic runtime missing resolver")
            if str(version.get("resolver") or "") != str(entry.get("resolver") or ""):
                row["findings"].append("resolver mismatch")
            directory = str((runtime.get("installation") or {}).get("directory") or "")
            if not directory.startswith("/"):
                row["findings"].append("installation directory must be absolute")
            row["findings"].extend(_network_findings(runtime))
            row["findings"].extend(_placeholder_findings(runtime))
            hard = [f for f in row["findings"] if not f.startswith("unclassified runtime placeholder")]
            row["catalog_contract"] = "ready" if not hard else "failed"
            row["agent_contract"] = "contract_ready" if not hard and provider in EXECUTABLE_PROVIDERS else "partial"
            if entry.get("compatibility_note"):
                row["specialized_contract"] = True
                row["compatibility_note"] = entry["compatibility_note"]
        rows.append(row)
        summary = games.setdefault(game, {"runtimes": 0, "contract_ready": 0, "partial": 0})
        summary["runtimes"] += 1
        if row["agent_contract"] == "contract_ready":
            summary["contract_ready"] += 1
        else:
            summary["partial"] += 1
        if row["catalog_contract"] != "ready":
            errors.append(f"{rid}: " + "; ".join(row["findings"]))
    published_ids = {str(e.get("id") or "") for e in published}
    orphan = sorted(rid for rid in files if rid not in published_ids)
    return {
        "schema_version": 1,
        "kind": "CatalogRuntimeReadinessAudit",
        "summary": {
            "supported_games": len(games), "published_runtimes": len(rows),
            "contract_ready_runtimes": sum(1 for row in rows if row["agent_contract"] == "contract_ready"),
            "partial_runtimes": sum(1 for row in rows if row["agent_contract"] != "contract_ready"),
            "live_binary_e2e_proven": 0,
            "deferred_runtimes": len(matrix.get("deferred_runtimes") or []),
        },
        "games": games, "runtimes": rows, "orphan_runtime_definitions": orphan,
        "errors": errors,
        "interpretation": {
            "contract_ready": "Catalog definition is internally consistent with the generic Agent/provider boundary.",
            "live_binary_e2e_not_proven": "Static CI does not claim that the upstream dedicated-server binary was downloaded and launched successfully.",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true", help="fail on catalog contract errors")
    args = parser.parse_args()
    result = audit()
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        s = result["summary"]
        print(f"catalog runtime readiness: {s['supported_games']} games, {s['published_runtimes']} runtimes, {s['contract_ready_runtimes']} contract-ready, {s['partial_runtimes']} partial")
        for error in result["errors"]:
            print(f"ERROR: {error}", file=sys.stderr)
    return 1 if args.strict and result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
