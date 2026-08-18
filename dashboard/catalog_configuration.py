"""Safe catalog configuration management surface."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CATALOG_EDITABLE_SUFFIXES = {
    ".json",
    ".cfg",
    ".conf",
    ".ini",
    ".properties",
    ".toml",
    ".yaml",
    ".yml",
}


@dataclass(frozen=True)
class CatalogFile:
    path: str
    size: int
    editable: bool


class CatalogConfigurationService:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.catalog_root = (
            self.root / "catalog"
        ).resolve()

    def _resolve(
        self,
        relative_path: str,
    ) -> Path:
        relative_path = str(relative_path).strip()

        if not relative_path:
            raise ValueError("catalog path is required")

        relative = Path(relative_path)

        if relative.is_absolute():
            raise ValueError("absolute catalog path is not allowed")

        if ".." in relative.parts:
            raise ValueError("catalog path traversal is not allowed")

        target = (
            self.catalog_root / relative
        ).resolve()

        try:
            target.relative_to(self.catalog_root)
        except ValueError as exc:
            raise ValueError(
                "catalog path escapes catalog root"
            ) from exc

        if target.is_symlink():
            raise ValueError(
                "symbolic links are not accepted in catalog editing"
            )

        return target

    def list_files(self) -> list[dict[str, Any]]:
        result = []

        if not self.catalog_root.exists():
            return result

        for path in sorted(self.catalog_root.rglob("*")):
            if not path.is_file():
                continue

            relative = path.relative_to(
                self.catalog_root
            ).as_posix()

            result.append(
                {
                    "path": relative,
                    "size": path.stat().st_size,
                    "editable": (
                        path.suffix.lower()
                        in CATALOG_EDITABLE_SUFFIXES
                    ),
                }
            )

        return result

    def read(self, relative_path: str) -> dict[str, Any]:
        target = self._resolve(relative_path)

        if not target.is_file():
            raise ValueError("catalog file not found")

        if target.suffix.lower() not in CATALOG_EDITABLE_SUFFIXES:
            raise ValueError("catalog file type is not viewable here")

        text = target.read_text(
            encoding="utf-8",
            errors="strict",
        )

        return {
            "path": target.relative_to(
                self.catalog_root
            ).as_posix(),
            "content": text,
            "size": len(text.encode("utf-8")),
            "editable": True,
        }

    def validate_content(
        self,
        relative_path: str,
        content: str,
    ) -> None:
        target = self._resolve(relative_path)

        if target.suffix.lower() == ".json":
            try:
                json.loads(content)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid JSON: {exc}"
                ) from exc

    def write(
        self,
        relative_path: str,
        content: str,
    ) -> dict[str, Any]:
        target = self._resolve(relative_path)

        if target.suffix.lower() not in CATALOG_EDITABLE_SUFFIXES:
            raise ValueError("catalog file type is not editable")

        if not target.exists():
            raise ValueError("catalog file not found")

        if not target.is_file():
            raise ValueError("catalog target is not a file")

        self.validate_content(
            relative_path,
            content,
        )

        target.write_text(
            content,
            encoding="utf-8",
        )

        return self.read(relative_path)
