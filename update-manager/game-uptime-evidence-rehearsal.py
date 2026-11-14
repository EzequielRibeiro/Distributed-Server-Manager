#!/usr/bin/env python3
"""Evidence-checked disposable #928 rehearsal, never an updater/production entry.

All witnesses are injected test fixtures, NOT trustable production attestations.
Caller-provided authenticated_agent_id models the result of heartbeat auth;
a production integration would need a separately verified, durable source.
"""
from __future__ import annotations

from importlib.machinery import SourceFileLoader
import importlib.util
import os
import re
from pathlib import Path
from typing import Callable, Mapping, Any


class EvidenceSafetyError(RuntimeError):
    pass


def _load(name: str, path: Path):
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


_ROOT = Path(__file__).resolve().parents[1]
_COMPOSE = _load("dsm928_observed_compose", Path(__file__).with_name("game-uptime-isolated-compose.py"))
_AGENT = _load("dsm928_observed_agent_wire", _ROOT / "agents/linux/runtime/game_uptime_agent_wire.py")
_CONTROLLER = _load("dsm928_observed_controller_wire", _ROOT / "dashboard/game_uptime_heartbeat_compat.py")
_PIN = _load("dsm928_observed_pin", Path(__file__).with_name("game-uptime-supervisor-unit.py"))


def execute_observed_fixture(
    workspace: Path,
    units: list[str],
    *,
    heartbeat_probe: Mapping[str, Any],
    heartbeat_offer: Mapping[str, Any],
    authenticated_agent_id: str,
    minecraft_unit: str,
    observed_minecraft_unit: str,
    versions_dir: Path,
    supervisor_sha256: str,
    inspect_pinned: Callable[[str], Mapping],
    inspect: Callable[[str], Mapping],
    prepare_files: Callable[[], None],
    apply_files: Callable[[], None],
    rollback_files: Callable[[], None],
    apply_unit: Callable[[], None],
    rollback_unit: Callable[[], None],
    verify: Callable[[], None],
) -> dict:
    """Wire diagnostic + hashed pinned ExecStart + two game identities, /tmp only.

    PIN/heartbeat callbacks are synthetic, never sufficient to authorize a
    real release or an update. No I/O to Agent/Controller endpoints is done.
    """
    root = _COMPOSE._root(workspace, units)
    if (minecraft_unit not in units or len(units) < 2
            or not isinstance(authenticated_agent_id, str)
            or not re.fullmatch(r"fixture-[a-zA-Z0-9_-]+", authenticated_agent_id)
            or not isinstance(observed_minecraft_unit, str)
            or not re.fullmatch(
                r"capivara-instance-dsm928-[a-zA-Z0-9_-]+\.service",
                observed_minecraft_unit,
            )):
        raise EvidenceSafetyError("incomplete or non-disposable game and agent identities")
    pinned_root = Path(versions_dir)
    if (pinned_root.is_symlink() or not pinned_root.is_dir()
            or root not in pinned_root.resolve(strict=True).parents
            or pinned_root.stat().st_uid != os.geteuid()
            or pinned_root.stat().st_mode & 0o022):
        raise EvidenceSafetyError("pinned evidence must use a private disposable versions directory")
    # Require the exact response that the Controller's authenticated route
    # would produce. The request nonce, authenticated Agent ID, expected wire
    # contract and absence of commands are checked before invoking any apply.
    expected = _CONTROLLER.assess_authenticated_probe(
        heartbeat_probe, authenticated_agent_id=authenticated_agent_id,
    )
    if (type(heartbeat_offer) is not dict or heartbeat_offer != expected
            or _AGENT.verify_offer(heartbeat_probe, heartbeat_offer).get("wire_compatible") is not True
            or heartbeat_offer.get("live_no_drain_authorized") is not False):
        raise EvidenceSafetyError("authenticated heartbeat fixture evidence invalid")
    if _AGENT.WIRE_CONTRACT != _CONTROLLER.WIRE_CONTRACT:
        raise EvidenceSafetyError("Agent and Controller wire contracts differ")

    def observe_pin():
        try:
            verified = _PIN.verify_pinned_supervisor(
                observed_minecraft_unit,
                versions_dir=Path(versions_dir),
                expected_sha256=supervisor_sha256,
                inspect=inspect_pinned,
            )
            live = inspect(minecraft_unit)
            if (type(live.get("pid")) is not int
                    or type(live.get("started")) is not int
                    or verified["main_pid"] != live["pid"]
                    or verified["start_stamp"] != live["started"]
                    or live.get("state") != "active"):
                raise EvidenceSafetyError("pinned supervisor process identity differs from game")
            return verified
        except (_PIN.SupervisorUnitError, OSError, ValueError, TypeError, KeyError) as exc:
            raise EvidenceSafetyError("pinned supervisor observation invalid") from exc

    before = observe_pin()

    def verify_after():
        after = observe_pin()
        if any(after[k] != before[k]
               for k in ("sha256", "main_pid", "start_stamp", "unit")):
            raise EvidenceSafetyError("pinned process identity changed during disposable update")
        verify()

    receipt = _COMPOSE.execute_with_compatibility_gate(
        root, units,
        controller_contract=dict(_AGENT.WIRE_CONTRACT),
        agent_contract=dict(_CONTROLLER.WIRE_CONTRACT),
        supervisor_pinned_preview=True,
        inspect=inspect, prepare_files=prepare_files,
        apply_files=apply_files, rollback_files=rollback_files,
        apply_unit=apply_unit, rollback_unit=rollback_unit,
        verify=verify_after,
    )
    return {
        **receipt,
        "evidence_source": "injected_authenticated_heartbeat_and_mock_systemd",
        "heartbeat_envelope_compatible": True,
        "pinned_supervisor_observed": True,
        "live_no_drain_authorized": False,
    }
