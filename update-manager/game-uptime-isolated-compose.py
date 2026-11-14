#!/usr/bin/env python3
"""#928: compose file/update and systemd swap solely within a disposable fixture.

This is NOT wired to update.sh main(), to SystemdMaterializer.apply(), or to
Controller/Agent production. All actual steps are caller-provided, but the
operation is restricted to an owner-marked /tmp fixture and named disposable
dsm928-e2e-* units. Separate durable component journals remain mandatory.
"""
from __future__ import annotations

from importlib.machinery import SourceFileLoader
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
        failures = []
        # The unit callback MUST be safe when the unit swap was not reached.
        # A failed component rollback never prevents the other compensation.
        for name, action in (("unit", rollback_unit), ("files", rollback_files)):
            try:
                action()
            except Exception as exc:
                failures.append((name, type(exc).__name__))
        try:
            verify()
        except Exception as exc:
            failures.append(("verification", type(exc).__name__))
        if failures:
            raise CompositeSafetyError(
                "incomplete disposable component rollback: "
                + ", ".join(f"{name}={kind}" for name, kind in failures)
            )

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
