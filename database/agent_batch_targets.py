#!/usr/bin/env python3
"""Safe CSV target parsing shared by Agent SSH batch CLIs.

The CSV never accepts raw passwords. Authentication is expressed only as a
Controller-local password_file or identity_file path. Global CLI defaults may
be overridden per row.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_BATCH_TARGETS = 500
MAX_CONCURRENCY = 20


@dataclass(frozen=True)
class BatchTarget:
    host: str
    ssh_user: str
    ssh_port: int
    platform: str
    name: str | None = None
    password_file: str | None = None
    identity_file: str | None = None
    region_id: str | None = None
    datacenter_id: str | None = None


def _clean(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def normalize_concurrency(value: Any, *, default: int = 5) -> int:
    try:
        concurrency = int(value if value not in (None, "") else default)
    except (TypeError, ValueError) as exc:
        raise ValueError("--concurrency must be an integer") from exc
    if not 1 <= concurrency <= MAX_CONCURRENCY:
        raise ValueError(f"--concurrency must be between 1 and {MAX_CONCURRENCY}")
    return concurrency


def _port(value: Any) -> int:
    try:
        port = int(value or 22)
    except (TypeError, ValueError) as exc:
        raise ValueError("SSH port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ValueError("SSH port must be between 1 and 65535")
    return port


def _platform(value: Any) -> str:
    platform = str(value or "linux").strip().lower()
    if platform not in {"linux", "windows"}:
        raise ValueError("platform must be linux or windows")
    return platform


def target_from_values(
    *,
    host: Any,
    ssh_user: Any,
    ssh_port: Any = 22,
    platform: Any = "linux",
    name: Any = None,
    password_file: Any = None,
    identity_file: Any = None,
    region_id: Any = None,
    datacenter_id: Any = None,
) -> BatchTarget:
    host_value = _clean(host)
    user_value = _clean(ssh_user)
    password_value = _clean(password_file)
    identity_value = _clean(identity_file)
    if not host_value:
        raise ValueError("host is required")
    if not user_value:
        raise ValueError(f"SSH user is required for {host_value}")
    if password_value and identity_value:
        raise ValueError(f"{host_value}: use either password_file or identity_file, not both")
    return BatchTarget(
        host=host_value,
        ssh_user=user_value,
        ssh_port=_port(ssh_port),
        platform=_platform(platform),
        name=_clean(name),
        password_file=password_value,
        identity_file=identity_value,
        region_id=_clean(region_id),
        datacenter_id=_clean(datacenter_id),
    )


def load_csv_targets(path: str | Path, *, defaults: dict[str, Any] | None = None) -> list[BatchTarget]:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ValueError(f"hosts file not found: {source}")
    defaults = dict(defaults or {})
    try:
        handle = source.open("r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise ValueError(f"unable to read hosts file: {source}") from exc
    with handle:
        reader = csv.DictReader(handle)
        fields = {str(x or "").strip().lower() for x in (reader.fieldnames or [])}
        if "password" in fields or "ssh_password" in fields:
            raise ValueError("CSV must never contain raw passwords; use password_file")
        if "host" not in fields:
            raise ValueError("CSV must contain a host column")
        targets: list[BatchTarget] = []
        seen: set[tuple[str, int]] = set()
        for line_number, raw in enumerate(reader, start=2):
            row = {str(k or "").strip().lower(): v for k, v in raw.items()}
            if not any(_clean(v) for v in row.values()):
                continue
            try:
                target = target_from_values(
                    host=row.get("host"),
                    ssh_user=_clean(row.get("user")) or _clean(row.get("ssh_user")) or defaults.get("ssh_user"),
                    ssh_port=_clean(row.get("port")) or _clean(row.get("ssh_port")) or defaults.get("ssh_port", 22),
                    platform=_clean(row.get("platform")) or defaults.get("platform", "linux"),
                    name=row.get("name"),
                    password_file=_clean(row.get("password_file")) or defaults.get("password_file"),
                    identity_file=_clean(row.get("identity_file")) or defaults.get("identity_file"),
                    region_id=_clean(row.get("region")) or _clean(row.get("region_id")) or defaults.get("region_id"),
                    datacenter_id=_clean(row.get("datacenter")) or _clean(row.get("datacenter_id")) or defaults.get("datacenter_id"),
                )
            except ValueError as exc:
                raise ValueError(f"CSV line {line_number}: {exc}") from exc
            key = (target.host.lower(), target.ssh_port)
            if key in seen:
                raise ValueError(f"CSV line {line_number}: duplicate host/port {target.host}:{target.ssh_port}")
            seen.add(key)
            targets.append(target)
            if len(targets) > MAX_BATCH_TARGETS:
                raise ValueError(f"hosts file exceeds maximum of {MAX_BATCH_TARGETS} targets")
    if not targets:
        raise ValueError("hosts file contains no targets")
    return targets
