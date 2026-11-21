#!/usr/bin/env python3
"""Shared read-only #928 hold gate for Controller worker loops.

This is only a per-cycle gate. It does NOT attest that a prior operation has
quiesced, coordinate remote Agents, or grant a no-drain update.
"""
from __future__ import annotations

from pathlib import Path
import sys

_RUNTIME = Path(__file__).resolve().parents[2] / "agents" / "linux" / "runtime"
if str(_RUNTIME) not in sys.path:
    sys.path.append(str(_RUNTIME))

from game_uptime_maintenance_hold import observe


def maintenance_paused() -> bool:
    """Skip the next mutating cycle while local root-owned hold is present."""
    return observe()["active"]
