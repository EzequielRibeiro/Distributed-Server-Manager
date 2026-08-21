#!/usr/bin/env python3
"""Canonical/legacy RuntimeDefinition path resolution for Python consumers."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG_ROOT = PROJECT_ROOT / "catalog" / "v2"


def runtime_definition_files(catalog_root: Path | None = None) -> Iterator[Path]:
    """Yield RuntimeDefinition JSON paths, canonical first, without duplicates.

    ``catalog_root`` may be the v2 catalog root or a direct runtime fixture root.
    This keeps existing tests/custom callers compatible while allowing the
    repository to migrate to ``catalog/v2/games/<game>/runtimes``.
    """
    root = Path(catalog_root or DEFAULT_CATALOG_ROOT)
    seen: set[Path] = set()

    candidates = []
    canonical = root / "games"
    legacy = root / "runtimes"

    if canonical.is_dir():
        candidates.extend(sorted(canonical.glob("*/runtimes/*.json")))
    if legacy.is_dir():
        candidates.extend(sorted(legacy.rglob("*.json")))

    # Compatibility for callers that historically pass the runtime directory
    # itself (or a temporary fixture directory) instead of catalog/v2.
    if not candidates and root.is_dir():
        candidates.extend(sorted(root.rglob("*.json")))

    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        yield path


__all__ = ["DEFAULT_CATALOG_ROOT", "runtime_definition_files"]
