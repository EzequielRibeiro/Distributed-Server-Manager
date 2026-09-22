#!/usr/bin/env python3
"""Audit Catalog v2 runtimes against the pinned GameDig interoperability map."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog" / "v2"
COMPAT = CATALOG / "external-query-compatibility.json"
GAMES = CATALOG / "games"

_ALLOWED_STRATEGIES = {"direct", "direct_explicit", "direct_query_role", "offset", "fixed_default_query"}
_ALLOWED_STATUS = {"supported", "conditional"}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected object")
    return value


def _runtime_files() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(GAMES.glob("*/runtimes/*.json")):
        runtime = _load(path)
        runtime_id = str(runtime.get("id") or "")
        if runtime_id:
            result[runtime_id] = runtime
    return result


def _effective_profile(game_profile: Mapping[str, Any], runtime_id: str) -> dict[str, Any]:
    profile = {key: value for key, value in game_profile.items() if key != "runtime_overrides"}
    overrides = game_profile.get("runtime_overrides")
    if isinstance(overrides, Mapping):
        override = overrides.get(runtime_id)
        if isinstance(override, Mapping):
            profile.update(dict(override))
    return profile


def audit() -> dict[str, Any]:
    manifest = _load(COMPAT)
    source = manifest.get("source") or {}
    games = manifest.get("games") or {}
    runtimes = _runtime_files()
    errors: list[str] = []
    warnings: list[str] = []
    rows: list[dict[str, Any]] = []

    commit = str(source.get("commit") or "")
    if len(commit) != 40 or any(ch not in "0123456789abcdef" for ch in commit.lower()):
        errors.append("GameDig source commit must be a pinned 40-character SHA")

    published_games = {str(runtime.get("game") or "") for runtime in runtimes.values()}
    missing_games = sorted(published_games - set(games))
    orphan_games = sorted(set(games) - published_games)
    for game in missing_games:
        errors.append(f"published game has no external query profile: {game}")
    for game in orphan_games:
        warnings.append(f"external query profile has no published runtime: {game}")

    for runtime_id, runtime in sorted(runtimes.items()):
        game = str(runtime.get("game") or "")
        base = games.get(game)
        if not isinstance(base, Mapping):
            continue
        profile = _effective_profile(base, runtime_id)
        strategy = str(profile.get("strategy") or "")
        status = str(profile.get("status") or "")
        protocol = str(profile.get("protocol") or "")
        gamedig_type = str(profile.get("gamedig_type") or "")
        game_role = str(profile.get("game_role") or "")
        query_role = str(profile.get("query_role") or "")
        network = runtime.get("network") or {}
        ports = {
            str(item.get("name") or ""): item
            for item in network.get("ports") or []
            if isinstance(item, Mapping)
        }
        findings: list[str] = []

        if strategy not in _ALLOWED_STRATEGIES:
            findings.append(f"invalid strategy: {strategy!r}")
        if status not in _ALLOWED_STATUS:
            findings.append(f"invalid status: {status!r}")
        if not protocol:
            findings.append("protocol is required")
        if not gamedig_type:
            findings.append("gamedig_type is required")
        if game_role not in ports:
            findings.append(f"game role is not declared by runtime: {game_role}")

        if strategy == "direct_query_role":
            if query_role not in ports:
                findings.append(f"query role is not declared by runtime: {query_role}")
            if not str(profile.get("checker_type") or "").strip():
                findings.append("direct_query_role requires checker_type")

        if strategy == "offset":
            if query_role not in ports:
                findings.append(f"query role is not declared by runtime: {query_role}")
            else:
                expected = profile.get("offset")
                if not isinstance(expected, int):
                    findings.append("offset strategy requires integer offset")
                elif game_role in ports:
                    actual = int(ports[query_role].get("offset")) - int(ports[game_role].get("offset"))
                    if actual != expected:
                        findings.append(
                            f"query offset mismatch: runtime={actual} gamedig={expected}"
                        )

        if strategy == "fixed_default_query":
            if query_role not in ports:
                findings.append(f"query role is not declared by runtime: {query_role}")
            if status != "conditional":
                findings.append("fixed default query must be marked conditional")
            if not isinstance(profile.get("default_query_port"), int):
                findings.append("fixed default query requires default_query_port")
            if not str(profile.get("note") or "").strip():
                findings.append("fixed default query requires an interoperability note")

        if strategy == "direct_explicit" and not isinstance(profile.get("default_query_port"), int):
            findings.append("direct_explicit strategy requires default_query_port")

        if status == "conditional":
            warnings.append(f"{runtime_id}: conditional external query interoperability")

        if findings:
            errors.extend(f"{runtime_id}: {finding}" for finding in findings)

        rows.append(
            {
                "runtime_id": runtime_id,
                "game": game,
                "gamedig_type": gamedig_type,
                "protocol": protocol,
                "strategy": strategy,
                "status": status,
                "game_role": game_role,
                "query_role": query_role or None,
                "findings": findings,
            }
        )

    return {
        "schema_version": 1,
        "kind": "ExternalQueryCompatibilityAudit",
        "source": source,
        "summary": {
            "published_runtimes": len(runtimes),
            "published_games": len(published_games),
            "mapped_games": len(set(games) & published_games),
            "mapped_runtimes": len(rows),
            "conditional_runtimes": sum(1 for row in rows if row["status"] == "conditional"),
            "errors": len(errors),
            "warnings": len(warnings),
        },
        "runtimes": rows,
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    result = audit()
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        summary = result["summary"]
        print(
            "external query compatibility: "
            f"{summary['mapped_games']}/{summary['published_games']} games, "
            f"{summary['mapped_runtimes']}/{summary['published_runtimes']} runtimes, "
            f"{summary['errors']} errors, {summary['warnings']} warnings"
        )
        for warning in result["warnings"]:
            print(f"WARNING: {warning}")
        for error in result["errors"]:
            print(f"ERROR: {error}")
    return 1 if args.strict and result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
