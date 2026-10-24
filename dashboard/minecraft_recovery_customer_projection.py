"""Pure customer projection of a recovered installation warning.

The persisted provisioning row is immutable; only the customer-visible copy
may omit a terminal failure once the verified recovery gate is satisfied.
"""
from __future__ import annotations
from typing import Any


def visible_provision_after_recovery(
    provision: dict[str, Any] | None,
    recovery: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(provision, dict):
        return provision
    if (provision.get("status") == "failed"
        and isinstance(recovery, dict)
        and recovery.get("allow_clear_previous_failure") is True
        and recovery.get("status") == "recovered_verified"
        and recovery.get("healthy") is True
        and recovery.get("loader_verified") is True
        and recovery.get("failure_matches_recovery") is True):
        return None
    return provision
