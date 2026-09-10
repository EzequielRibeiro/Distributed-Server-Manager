"""Runtime-declared configuration surface."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Mapping


class ConfigurationManifestError(ValueError):
    """Invalid runtime configuration manifest."""


_ALLOWED_SOURCES = {"SYSTEM", "CONTRACT", "CUSTOMER"}
_ALLOWED_FORMATS = {"semicolon_properties", "equals_properties"}
_ALLOWED_PROPERTY_TYPES = {"string", "integer", "boolean"}


@dataclass(frozen=True)
class ConfigurationProperty:
    key: str
    source: str
    type: str = "string"

    def __post_init__(self):
        key = str(self.key).strip()
        source = str(self.source).strip().upper()
        property_type = str(self.type).strip().lower()

        if not key:
            raise ConfigurationManifestError(
                "configuration property key is required"
            )
        if source not in _ALLOWED_SOURCES:
            raise ConfigurationManifestError(
                f"unsupported configuration property source: {source}"
            )
        if property_type not in _ALLOWED_PROPERTY_TYPES:
            raise ConfigurationManifestError(
                f"unsupported configuration property type: {property_type}"
            )

        object.__setattr__(self, "key", key)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "type", property_type)


@dataclass(frozen=True)
class ConfigurationEntry:
    id: str
    path: str
    category: str = "game"
    label: str | None = None
    editable: bool = True
    optional: bool = False
    format: str | None = None
    properties: tuple[ConfigurationProperty, ...] = ()

    def __post_init__(self):
        normalized_id = str(self.id).strip().lower()
        normalized_path = str(self.path).strip().replace("\\", "/")
        normalized_category = str(self.category).strip().lower()
        normalized_format = (
            None
            if self.format is None
            else str(self.format).strip().lower()
        )

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

        if (
            normalized_format is not None
            and normalized_format not in _ALLOWED_FORMATS
        ):
            raise ConfigurationManifestError(
                f"unsupported configuration format: {normalized_format}"
            )

        property_keys: set[str] = set()

        for item in self.properties:
            if not isinstance(item, ConfigurationProperty):
                raise ConfigurationManifestError(
                    "invalid configuration property"
                )

            if item.key in property_keys:
                raise ConfigurationManifestError(
                    f"duplicate configuration property: {item.key}"
                )

            property_keys.add(item.key)

        if self.properties and normalized_format is None:
            raise ConfigurationManifestError(
                "managed configuration properties require a format"
            )

        object.__setattr__(self, "id", normalized_id)
        object.__setattr__(self, "path", str(candidate))
        object.__setattr__(self, "category", normalized_category)
        object.__setattr__(self, "format", normalized_format)


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

            raw_properties = raw_entry.get("properties", [])

            if raw_properties is None:
                raw_properties = []

            if not isinstance(raw_properties, list):
                raise ConfigurationManifestError(
                    "configuration properties must be an array"
                )

            properties: list[ConfigurationProperty] = []

            for raw_property in raw_properties:
                if not isinstance(raw_property, Mapping):
                    raise ConfigurationManifestError(
                        "configuration property must be an object"
                    )

                properties.append(
                    ConfigurationProperty(
                        key=str(
                            raw_property.get("key", "")
                        ).strip(),
                        source=str(
                            raw_property.get("source", "")
                        ).strip(),
                        type=str(
                            raw_property.get("type", "string")
                        ).strip(),
                    )
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
                format=(
                    None
                    if raw_entry.get("format") is None
                    else str(raw_entry.get("format"))
                ),
                properties=tuple(properties),
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
