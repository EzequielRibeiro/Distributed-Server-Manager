#!/usr/bin/env python3
"""Read-only completeness of a two-game no-drain rehearsal inventory.

The caller must name *every* game unit expected to remain active. A successful
two-point inventory is only a candidate for a disposable test, not uptime
proof across an update, and never grants a production update permission.
"""
from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

_UNIT = re.compile(r"capivara-instance-[A-Za-z0-9_.-]+\.service\Z")
_FAMILIES = ("minecraft", "dayz")


def assess(expected_active_units: list[str] | None,
           observed_inventory: Mapping[str, Any] | None) -> dict[str, Any]:
    blockers: list[str] = []
    expected: list[str] = []
    if expected_active_units is None:
        blockers.append("expected_active_units_not_declared")
    elif not isinstance(expected_active_units, list) or any(
        not isinstance(name, str) or not _UNIT.fullmatch(name)
        for name in expected_active_units
    ) or len(set(expected_active_units)) != len(expected_active_units):
        blockers.append("invalid_expected_active_unit_set")
    else:
        expected = sorted(expected_active_units)
        for family in _FAMILIES:
            if not any("-" + family + "-" in name for name in expected):
                blockers.append(f"expected_{family}_service_missing")
    if not isinstance(observed_inventory, Mapping):
        blockers.append("active_inventory_missing")
        rows = []
    elif observed_inventory.get("inventory_error"):
        blockers.append("active_inventory_failed")
        rows = []
    else:
        rows = observed_inventory.get("units")
        if not isinstance(rows, list):
            rows = []
            blockers.append("active_inventory_invalid")
        if type(observed_inventory.get("managed_active_units")) is not int or (
            observed_inventory["managed_active_units"] != len(rows)
        ):
            blockers.append("active_inventory_count_mismatch")

    actual: list[str] = []
    unverified: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            blockers.append("active_inventory_malformed_row")
            continue
        unit = row.get("unit")
        if not isinstance(unit, str) or not _UNIT.fullmatch(unit):
            blockers.append("active_inventory_invalid_unit")
            continue
        actual.append(unit)
        if (row.get("identity_verified") is not True
                or type(row.get("main_pid")) is not int
                or row["main_pid"] <= 1
                or type(row.get("start_stamp")) is not int
                or row["start_stamp"] <= 0):
            unverified.append(unit)
    if len(actual) != len(set(actual)):
        blockers.append("active_inventory_duplicate_unit")
    missing = sorted(set(expected) - set(actual))
    unexpected = sorted(set(actual) - set(expected))
    if missing:
        blockers.append("expected_active_service_not_running")
    if unexpected:
        blockers.append("unexpected_active_service_requires_reconciliation")
    if unverified:
        blockers.append("active_process_identity_unverified")
    return {
        "kind": "CapivaraNoDrainOperationalCoverage",
        "schema_version": 1,
        "scope": "read_only_current_process_inventory_not_continuous_uptime",
        "expected_active_units": expected,
        "observed_active_units": sorted(actual),
        "missing_active_units": missing,
        "unexpected_active_units": unexpected,
        "unverified_units": sorted(unverified),
        "blockers": sorted(set(blockers)),
        "verified_for_disposable_rehearsal": not blockers,
        "live_no_drain_authorized": False,
    }
