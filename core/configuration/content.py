"""Mod/plugin configuration categorization."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable


def group_configuration_entries(
    entries: Iterable[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for entry in entries:
        category = str(
            entry.get("category", "game")
        ).strip().lower()

        grouped[category].append(dict(entry))

    return {
        category: sorted(
            values,
            key=lambda item: (
                str(item.get("label") or item.get("id")),
                str(item.get("path")),
            ),
        )
        for category, values in grouped.items()
    }
