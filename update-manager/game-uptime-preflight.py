#!/usr/bin/env python3
"""Read-only per-unit DSM update impact preflight. Never authorizes no-drain."""
from __future__ import annotations

import argparse
import importlib.util
import json
from importlib.machinery import SourceFileLoader
from pathlib import Path


def _load(name: str, filename: str):
    loader = SourceFileLoader(name, str(Path(__file__).with_name(filename)))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


plan = _load("game_uptime_plan", "game-uptime-plan.py")
reporter = _load("game_uptime_report", "game-uptime-report.py")


def preflight(installed: Path, target: Path, *, list_units=None, inspect=None):
    """Report *current updater* behavior, not a hypothetical permission to update."""
    state = {"kind": "CapivaraDSMNoDrainPreflight", "schema_version": 1,
             "mode": "read_only", "live_no_drain_authorized": False,
             "current_updater_drains_active_games": True,
             "planned_control_plane_actions": ["stop_dsm_services", "update_dsm",
                                                "restart_dsm_services"],
             "planned_game_actions": [], "units": []}
    try:
        impact = plan.analyze(installed, target)
        units = reporter.report(list_units=list_units, inspect=inspect)
        state["release_impact"] = impact
        if units.get("inventory_error"):
            state.update(classification="blocked", requires_game_drain=True,
                         reason="Cannot establish complete game service inventory: " +
                                str(units["inventory_error"])[:200])
            return state
        for item in units["units"]:
            verified = item["identity_verified"]
            reason = (str(item.get("reason") or "unverified")) if not verified else (
                "Current update.sh unconditionally drains active managed games; "
                "no-drain transaction is not implemented")
            state["units"].append({"unit": item["unit"], "current_action": "stop_and_restart",
                                   "no_drain_candidate": bool(verified and
                                      not impact["requires_game_drain"]),
                                   "no_drain_authorized": False, "reason": reason})
            state["planned_game_actions"].append({"unit": item["unit"],
                                                   "action": "stop_and_restart"})
        state["classification"] = ("maintenance_required" if
                                    impact["requires_game_drain"] else "review_only")
        state["requires_game_drain"] = True if state["units"] else impact["requires_game_drain"]
        state["reason"] = ("Current update.sh drains all active managed games. "
                           "Potential no-drain candidates require independent "
                           "transaction, rollback and PID preservation tests.")
    except (OSError, ValueError) as exc:
        state.update(classification="blocked", requires_game_drain=True,
                     reason=f"Cannot classify release safely: {str(exc)[:200]}")
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("installed", type=Path)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    result = preflight(args.installed, args.target)
    print(json.dumps(result, ensure_ascii=False))
    return 2 if result["classification"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
