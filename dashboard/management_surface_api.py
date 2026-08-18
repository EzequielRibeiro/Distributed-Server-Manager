"""Integrated management-surface helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from catalog_configuration_api import (
    list_catalog_files_for_user,
    read_catalog_file_for_user,
    write_catalog_file_for_user,
)
from location_api import (
    datacenters_for_user,
    placement_candidates_for_user,
    regions_for_user,
)


def management_summary(
    user: dict[str, Any] | None,
    backend,
    root: Path,
):
    if not user:
        raise PermissionError("authentication required")

    role = str(user.get("role", "")).lower()

    return {
        "role": role,
        "regions": regions_for_user(
            user,
            backend,
        ),
        "datacenters": datacenters_for_user(
            user,
            backend,
        ),
        "catalog": list_catalog_files_for_user(
            user,
            root,
        ),
    }


__all__ = [
    "management_summary",
    "list_catalog_files_for_user",
    "read_catalog_file_for_user",
    "write_catalog_file_for_user",
    "regions_for_user",
    "datacenters_for_user",
    "placement_candidates_for_user",
]
