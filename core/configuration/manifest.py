"""Runtime-declared configuration surface."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Mapping


class ConfigurationManifestError(ValueError):
    """Invalid runtime configuration manifest."""


@dataclass(frozen=True)
class ConfigurationEntry:
    id: str
    path: str
    category: str = "game"
    label: str | None = None
    editable: bool = True
    optional: bool = False

    def __post_init__(self):
        normalized_id = str(self.id).strip().lower()
        normalized_path = str(self.path).strip().replace("\\", "/")
        normalized_category = str(self.category).strip().lower()

        if not normalized_id:
            raise ConfigurationManifestError(
                "configuration id is required"
            )

        if not normalized_path:
            raise ConfigurationManifestError(
                "configuration path is required"
            )

        candidate = PurePosixPath(normalized_path)

        if candidate.is_absolute() or ".." in candidate.parts:
            raise ConfigurationManifestError(
                "configuration path must remain relative"
            )

        if normalized_category not in {
            "game",
            "mod",
            "plugin",
            "runtime",
        }:
            raise ConfigurationManifestError(
                "unsupported configuration category"
            )

        object.__setattr__(self, "id", normalized_id)
        object.__setattr__(self, "path", str(candidate))
        object.__setattr__(self, "category", normalized_category)


@dataclass(frozen=True)
class ConfigurationManifest:
    entries: tuple[ConfigurationEntry, ...]

    @classmethod
    def from_runtime_definition(
        cls,
        definition: Mapping[str, Any],
    ) -> "ConfigurationManifest":
        raw = definition.get("configuration", {})

        if raw is None:
            raw = {}

        if not isinstance(raw, Mapping):
            raise ConfigurationManifestError(
                "runtime configuration must be an object"
            )

        raw_files = raw.get("files", [])

        if not isinstance(raw_files, list):
            raise ConfigurationManifestError(
                "configuration.files must be an array"
            )

        entries: list[ConfigurationEntry] = []
        ids: set[str] = set()
        paths: set[str] = set()

        for raw_entry in raw_files:
            if not isinstance(raw_entry, Mapping):
                raise ConfigurationManifestError(
                    "configuration file entry must be an object"
                )

            entry = ConfigurationEntry(
                id=str(raw_entry.get("id", "")).strip(),
                path=str(raw_entry.get("path", "")).strip(),
                category=str(
                    raw_entry.get("category", "game")
                ).strip(),
                label=(
                    None
                    if raw_entry.get("label") is None
                    else str(raw_entry.get("label"))
                ),
                editable=bool(
                    raw_entry.get("editable", True)
                ),
                optional=bool(
                    raw_entry.get("optional", False)
                ),
            )

            if entry.id in ids:
                raise ConfigurationManifestError(
                    f"duplicate configuration id: {entry.id}"
                )

            if entry.path in paths:
                raise ConfigurationManifestError(
                    f"duplicate configuration path: {entry.path}"
                )

            ids.add(entry.id)
            paths.add(entry.path)
            entries.append(entry)

        return cls(entries=tuple(entries))

    @property
    def paths(self) -> set[str]:
        return {entry.path for entry in self.entries}
