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
compatibility = _load("game_uptime_compatibility", "game-uptime-compatibility.py")
supervisor_unit = _load("game_uptime_supervisor_unit", "game-uptime-supervisor-unit.py")
coverage = _load("game_uptime_coverage", "game-uptime-coverage.py")


def _pinned_minecraft_evidence(units, *, versions_dir, expected_sha256, inspect):
    """Bind the *same* active unit's PID/start stamp to its versioned ExecStart.

    A caller-provided bool is never accepted as a substitute for systemd proof.
    """
    minecraft = [item for item in units if "minecraft" in item["unit"].lower()]
    if not minecraft:
        return {"verified": True, "scope": "no_active_minecraft", "observations": [],
                "blockers": []}
    if versions_dir is None or expected_sha256 is None:
        return {"verified": False, "scope": "active_minecraft", "observations": [],
                "blockers": ["pinned_supervisor_evidence_missing"]}
    observations = []
    blockers = []
    verify = inspect if inspect is not None else reporter.guard.inspect
    for item in minecraft:
        if not item.get("identity_verified"):
            blockers.append(item["unit"] + ":initial_identity_unverified")
            continue
        try:
            result = supervisor_unit.verify_pinned_supervisor(
                item["unit"], versions_dir=Path(versions_dir),
                expected_sha256=expected_sha256, inspect=verify,
            )
            if (item.get("main_pid") != result["main_pid"] or
                    not isinstance(item.get("start_stamp"), int) or
                    item["start_stamp"] != result["start_stamp"]):
                raise supervisor_unit.SupervisorUnitError("process identity changed between inspections")
            observations.append(result)
        except (supervisor_unit.SupervisorUnitError, OSError, ValueError,
                TypeError, KeyError) as exc:
            blockers.append(item["unit"] + ":" + str(exc)[:160])
    return {"verified": not blockers and len(observations) == len(minecraft),
            "scope": "active_minecraft", "observations": observations,
            "blockers": blockers}



def _handoff_witness(inventory, *, list_units=None, inspect=None):
    """Re-read the *complete* active set and each PID/unit hash before a handoff.

    This is a read-only two-point race guard, not a process lock or a grant to
    update. Continuous uptime still requires a transaction and post-rollback
    verification. Never persist ExecStart, EnvironmentFiles or secrets here.
    """
    result = {"kind": "CapivaraNoDrainHandoffWitness", "schema_version": 1,
              "mode": "read_only", "verified_for_disposable_rehearsal": False,
              "live_no_drain_authorized": False, "blockers": []}
    blockers = result["blockers"]
    if inventory.get("inventory_error"):
        blockers.append("initial_game_inventory_failed")
        return result
    original = inventory.get("units")
    if not isinstance(original, list):
        blockers.append("initial_game_inventory_invalid")
        return result
    known = {}
    for item in original:
        if not isinstance(item, dict):
            blockers.append("initial_game_record_invalid")
            continue
        name = item.get("unit")
        if not isinstance(name, str) or not reporter.guard.UNIT.fullmatch(name) or name in known:
            blockers.append("initial_game_unit_set_invalid")
            continue
        if item.get("identity_verified") is not True:
            blockers.append("initial_game_identity_unverified")
        for key in ("main_pid", "start_stamp"):
            value = item.get(key)
            if type(value) is not int or value <= (1 if key == "main_pid" else 0):
                blockers.append("initial_game_identity_incomplete")
        digest = item.get("unit_config_sha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(
                char not in "0123456789abcdef" for char in digest):
            blockers.append("initial_game_unit_witness_missing")
        known[name] = item
    if blockers:
        result["blockers"] = sorted(set(blockers))
        return result
    try:
        # Re-list, not only re-inspect known PIDs. A newly started game must
        # block the handoff as surely as a removed or replaced game.
        current = (list_units or reporter._list_units)()
        if (not isinstance(current, list)
                or any(not isinstance(name, str)
                       or not reporter.guard.UNIT.fullmatch(name) for name in current)
                or len(current) != len(set(current))
                or sorted(current) != sorted(known)):
            blockers.append("active_game_unit_set_changed")
        else:
            observer = inspect or reporter.guard.inspect
            for name in sorted(current):
                now = observer(name)
                initial = known[name]
                if (not isinstance(now, dict) or
                        now.get("main_pid") != initial["main_pid"] or
                        now.get("start_stamp") != initial["start_stamp"] or
                        now.get("unit_config_sha256") != initial["unit_config_sha256"]):
                    blockers.append("active_game_pid_or_unit_witness_changed")
    except Exception:
        # A failed systemd read is a blocker, never permission to continue.
        blockers.append("second_game_inventory_or_identity_read_failed")
    result["blockers"] = sorted(set(blockers))
    result["verified_for_disposable_rehearsal"] = not blockers
    result["active_units_witnessed"] = len(known)
    return result


def preflight(installed: Path, target: Path, *, list_units=None, inspect=None,
              controller_contract=None, agent_contract=None, supervisor_pinned=False,
              supervisor_versions_dir=None, supervisor_expected_sha256=None,
              expected_active_units=None):
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
        operational_coverage = coverage.assess(expected_active_units, units)
        state["operational_coverage"] = operational_coverage
        # Both inventory and process witnesses must still agree when entering
        # a future transaction. A single initial sample is insufficient.
        witness = _handoff_witness(units, list_units=list_units, inspect=inspect)
        state["handoff_witness"] = witness
        state["no_drain_handoff_witness_verified"] = witness["verified_for_disposable_rehearsal"]
        state["no_drain_operational_coverage_verified"] = (
            operational_coverage["verified_for_disposable_rehearsal"]
        )
        # Independent, fail-closed gate: legacy candidate means only worth review,
        # never process-safe. Controller/Agent declarations are not inferred.
        pin = _pinned_minecraft_evidence(
            units["units"], versions_dir=supervisor_versions_dir,
            expected_sha256=supervisor_expected_sha256, inspect=inspect,
        )
        # The legacy supervisor_pinned flag cannot self-authorize isolation.
        # Only an independently inspected, same-PID/start-stamp systemd witness
        # may elevate the compatibility diagnostic to further rehearsal.
        gate = compatibility.assess(
            installed, target, controller_contract, agent_contract,
            minecraft_active=any("minecraft" in item["unit"].lower()
                                 for item in units["units"]),
            supervisor_pinned=pin["verified"],
        )
        state["supervisor_pin_evidence"] = pin
        state["compatibility_gate"] = gate
        state["no_drain_compatibility_verified"] = gate["compatible_for_further_rehearsal"]
        state["no_drain_disposable_rehearsal_candidate"] = bool(
            not impact["requires_game_drain"]
            and operational_coverage["verified_for_disposable_rehearsal"]
            and witness["verified_for_disposable_rehearsal"]
            and gate["compatible_for_further_rehearsal"]
        )
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
                                   "no_drain_authorized": False,
                                   "no_drain_compatibility_verified": bool(verified and gate["compatible_for_further_rehearsal"]),
                                   "reason": reason})
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
