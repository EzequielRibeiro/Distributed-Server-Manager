"""Configuration management subsystem for Capivara DSM."""

from .manifest import (
    ConfigurationEntry,
    ConfigurationManifest,
    ConfigurationManifestError,
)

__all__ = [
    "ConfigurationEntry",
    "ConfigurationManifest",
    "ConfigurationManifestError",
]
