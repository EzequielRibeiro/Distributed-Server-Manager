#!/usr/bin/env python3
"""#928: compose file/update and systemd swap solely within a disposable fixture.

This is NOT wired to update.sh main(), to SystemdMaterializer.apply(), or to
Controller/Agent production. All actual steps are caller-provided, but the
operation is restricted to an owner-marked /tmp fixture and named disposable
dsm928-e2e-* units. Separate durable component journals remain mandatory.
"""
from __future__ import annotations

from importlib.machinery import SourceFileLoader
import json
import importlib.util
from pathlib import Path
import os
import re
import stat
import tempfile
from typing import Callable, Mapping

_LOADER = SourceFileLoader(
    "dsm928_isolated_composite_transaction",
    str(Path(__file__).with_name("game-uptime-transaction.py")),
)
_SPEC = importlib.util.spec_from_loader(_LOADER.name, _LOADER)
_TRANSACTION = importlib.util.module_from_spec(_SPEC)
_LOADER.exec_module(_TRANSACTION)

_MARKER = b"DSM928_DISPOSABLE_FIXTURE_V1\n"
_UNIT = re.compile(r"dsm928-e2e-[a-z0-9-]+\.service\Z")


class CompositeSafetyError(RuntimeError):
    pass


def _root(workspace: Path, units: list[str]) -> Path:
    root = Path(workspace)
    if root.is_symlink() or not root.is_dir():
        raise CompositeSafetyError("disposable filesystem workspace is missing or symlinked")
    resolved = root.resolve(strict=True)
    temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
    if resolved == temp_root or temp_root not in resolved.parents:
        raise CompositeSafetyError("composite must stay within an isolated /tmp workspace")
    identity = resolved / "fixture-owner"
    if (identity.is_symlink() or not identity.is_file()
            or identity.read_bytes() != _MARKER):
        raise CompositeSafetyError("missing disposable fixture ownership marker")
    if not isinstance(units, list) or not units or any(
        not isinstance(unit, str) or not _UNIT.fullmatch(unit)
        for unit in units
    ) or len(set(units)) != len(units):
        raise CompositeSafetyError("only unique dsm928-e2e units are permitted")
    # Refuse any pre-existing production DSM storage in the fixture.
    if (resolved / "installed").is_symlink():
        raise CompositeSafetyError("symlinked disposable installed product")
    if not (resolved / "installed").is_dir() or not (resolved / "new-payload").is_dir():
        raise CompositeSafetyError("missing disposable update fixtures")
    return resolved


def _compensate(*, rollback_unit, rollback_files, verify, restore_unit=True):
    """Attempt both components, even when the first rollback fails."""
    errors = []
    callbacks = (
        (("unit", rollback_unit),) if restore_unit else ()
    ) + (("files", rollback_files), ("verification", verify))
    for name, callback in callbacks:
        try:
            callback()
        except Exception as exc:
            errors.append((name, type(exc).__name__))
    if errors:
        raise CompositeSafetyError(
            "incomplete disposable component rollback: "
            + ", ".join(f"{name}={kind}" for name, kind in errors)
        )


def _inspect_unit_recovery(root: Path, units: list[str]) -> bool:
    """Validate optional independently durable swap journal before recovery.

    Missing unit journal means the unit component was not applied. A valid
    terminal restored/rolled-back journal needs no repeated compensation.
    """
    path = root / "dsm928-unit-swap.json"
    if not path.exists() and not path.is_symlink():
        return False
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8192:
        raise CompositeSafetyError("unsafe disposable unit component journal")
    try:
        with path.open("r", encoding="utf-8") as stream:
            raw = stream.read(8193)
        if len(raw) > 8192:
            raise ValueError("oversized component journal")
        record = json.loads(raw)
    except (OSError, ValueError, UnicodeError) as exc:
        raise CompositeSafetyError("unreadable disposable unit component journal") from exc
    if (not isinstance(record, dict)
            or record.get("kind") != "DSM928DisposableSystemdSwap"
            or record.get("scope") != "disposable_only_not_production"
            or record.get("live_no_drain_authorized") is not False
            or record.get("unit") not in units):
        raise CompositeSafetyError("unit component journal is not authorized for recovery")
    status = record.get("status")
    if status in {"restored", "rolled_back"}:
        return False
    if status in {"applied", "prepared"}:
        return True
    raise CompositeSafetyError("interrupted or unsafe unit component recovery state")


def execute(
    workspace: Path,
    units: list[str],
    *,
    inspect: Callable[[str], Mapping],
    prepare_files: Callable[[], None],
    apply_files: Callable[[], None],
    rollback_files: Callable[[], None],
    apply_unit: Callable[[], None],
    rollback_unit: Callable[[], None],
    verify: Callable[[], None],
) -> dict:
    """Apply fixture file functions + systemd swap; compensate in reverse order.

    Component-specific callbacks must themselves restrict all file/systemd
    paths. This wrapper enforces order, immutable PID/start checks via the
    underlying transaction, replay denial, and compensates *both* components
    even if one rollback operation fails.
    """
    root = _root(workspace, units)
    actions = (inspect, prepare_files, apply_files, rollback_files,
               apply_unit, rollback_unit, verify)
    if any(not callable(action) for action in actions):
        raise CompositeSafetyError("every callback must be callable")
    journal = root / "dsm928-composite-journal"
    if journal.exists() or journal.is_symlink():
        raise CompositeSafetyError("existing composite transaction requires manual review")
    journal.mkdir(mode=0o700)
    if journal.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise CompositeSafetyError("composite transaction journal must be private")

    # Backup fixture files before starting the process-preservation transaction.
    # If this fails, there are no changes to compensate.
    prepare_files()

    def apply() -> None:
        apply_files()
        apply_unit()
        verify()

    def rollback() -> None:
        _compensate(rollback_unit=rollback_unit,
                    rollback_files=rollback_files, verify=verify)

    result = _TRANSACTION.execute(
        journal, units, inspect=inspect, apply=apply, rollback=rollback,
    )
    if result["status"] != "verified" or result["live_no_drain_authorized"] is not False:
        raise CompositeSafetyError("unverified disposable composite transaction")
    return {
        "kind": "DSM928DisposableComposedUpgrade",
        "status": result["status"],
        "scope": "disposable_only_not_production",
        "original_units": result["units"],
        "live_no_drain_authorized": False,
    }



def execute_with_compatibility_gate(
    workspace: Path,
    units: list[str],
    *,
    controller_contract: Mapping | None,
    agent_contract: Mapping | None,
    supervisor_pinned_preview: bool,
    inspect: Callable[[str], Mapping],
    prepare_files: Callable[[], None],
    apply_files: Callable[[], None],
    rollback_files: Callable[[], None],
    apply_unit: Callable[[], None],
    rollback_unit: Callable[[], None],
    verify: Callable[[], None],
) -> dict:
    """Conservatively connect diagnostic compatibility to disposable execution.

    The contracts and pinned preview are test inputs, not authenticated
    production evidence. Even a passing assessment is NEVER release approval.
    """
    root = _root(workspace, units)
    compatibility_loader = SourceFileLoader(
        "dsm928_composite_compatibility",
        str(Path(__file__).with_name("game-uptime-compatibility.py")),
    )
    compatibility_spec = importlib.util.spec_from_loader(
        compatibility_loader.name, compatibility_loader,
    )
    compatibility = importlib.util.module_from_spec(compatibility_spec)
    compatibility_loader.exec_module(compatibility)
    assessment = compatibility.assess(
        root / "installed", root / "new-payload",
        controller_contract, agent_contract,
        minecraft_active=True,
        supervisor_pinned=supervisor_pinned_preview is True,
    )
    if (
        assessment.get("live_no_drain_authorized") is not False
        or assessment.get("compatible_for_further_rehearsal") is not True
        or assessment.get("blockers")
    ):
        raise CompositeSafetyError(
            "disposable compatibility gate blocked: "
            + ", ".join(assessment.get("blockers") or ["invalid_diagnostic"])
        )
    result = execute(
        root, units, inspect=inspect,
        prepare_files=prepare_files, apply_files=apply_files,
        rollback_files=rollback_files, apply_unit=apply_unit,
        rollback_unit=rollback_unit, verify=verify,
    )
    # A synthetic successful contract match is only permission to run a
    # disposable rehearsal. It MUST NOT be promoted to production approval.
    return {
        **result,
        "compatibility_source": "synthetic_disposable_fixture",
        "controller_agent_contract_compatible": True,
        "live_no_drain_authorized": False,
    }


def recover_interrupted(
    workspace: Path,
    units: list[str],
    *,
    inspect: Callable[[str], Mapping],
    rollback_files: Callable[[], None],
    rollback_unit: Callable[[], None],
    verify: Callable[[], None],
    operator_reviewed: bool = False,
) -> dict:
    """Manual-only recovery of *both* components after abrupt interruption.

    Only a private owner-marked /tmp fixture with a durable prepared/applied
    transaction and an available file backup can be restored. Unit journal
    must live at the same fixture root; external journals require separately
    reviewed recovery and are intentionally unsupported by this prototype.
    """
    root = _root(workspace, units)
    if operator_reviewed is not True:
        raise CompositeSafetyError("explicit operator review is required")
    if any(not callable(c) for c in
           (inspect, rollback_files, rollback_unit, verify)):
        raise CompositeSafetyError("every recovery callback must be callable")
    journal = root / "dsm928-composite-journal"
    if (journal.is_symlink() or not journal.is_dir()
            or journal.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO)):
        raise CompositeSafetyError("missing or unsafe composite transaction journal")
    backups = root / "backups"
    if backups.is_symlink() or not backups.is_dir():
        raise CompositeSafetyError("missing disposable update backup")
    artifacts = list(backups.glob("dsm-before-update-*.tar.gz"))
    if (len(artifacts) != 1 or artifacts[0].is_symlink()
            or not artifacts[0].is_file() or artifacts[0].stat().st_size == 0):
        raise CompositeSafetyError("ambiguous or unsafe disposable file backup")
    restore_unit = _inspect_unit_recovery(root, units)

    def rollback() -> None:
        _compensate(rollback_unit=rollback_unit,
                    rollback_files=rollback_files,
                    verify=verify, restore_unit=restore_unit)

    result = _TRANSACTION.recover_interrupted(
        journal, units, inspect=inspect, rollback=rollback,
        operator_reviewed=True,
    )
    if result["status"] != "recovered_rollback" or result["live_no_drain_authorized"] is not False:
        raise CompositeSafetyError("unverified disposable composite recovery")
    return {
        "kind": "DSM928DisposableComposedUpgrade",
        "scope": "disposable_only_not_production",
        "status": "recovered_rollback",
        "original_units": result["units"],
        "live_no_drain_authorized": False,
    }
