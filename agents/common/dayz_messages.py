#!/usr/bin/env python3
"""DayZ native server-message planning shared by Linux and Windows Agents.

Filesystem targets are derived from the Agent-owned RuntimeSpec.  The Controller
supplies only maintenance timing; it never supplies a path or raw XML.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from typing import Any
from xml.etree import ElementTree as ET

_CONFIG_ARG = re.compile(r"^-config=(.+)$", re.IGNORECASE)
_MISSION_ARG = re.compile(r"^-mission=(.+)$", re.IGNORECASE)
_TEMPLATE = re.compile(r"\btemplate\s*=\s*[\"']([^\"']+)[\"']\s*;", re.IGNORECASE)
_SAFE_MISSION = re.compile(r"^[A-Za-z0-9._-]{1,191}$")
MANAGED_TEXT = "Capivara maintenance: #name will restart in #tmin minutes."


class DayZMessagesError(ValueError):
    pass


@dataclass(frozen=True)
class DayZShutdownMessage:
    deadline_minutes: int
    text: str = MANAGED_TEXT

    def validate(self) -> None:
        if not isinstance(self.deadline_minutes, int) or isinstance(self.deadline_minutes, bool):
            raise DayZMessagesError("deadline_minutes must be an integer")
        if self.deadline_minutes < 1 or self.deadline_minutes > 10080:
            raise DayZMessagesError("deadline_minutes must be between 1 and 10080")
        text = str(self.text or "").strip()
        if not text:
            raise DayZMessagesError("text must not be empty")
        if len(text) > 160:
            raise DayZMessagesError("text must be at most 160 characters")
        if "\x00" in text:
            raise DayZMessagesError("text contains NUL")


@dataclass(frozen=True)
class DayZNativeRestartPlan:
    instance_id: str
    mission: str
    messages_path: str
    message: DayZShutdownMessage
    xml: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "CapivaraDayZNativeRestartPlan",
            "instance_id": self.instance_id,
            "mission": self.mission,
            "messages_path": self.messages_path,
            "deadline_minutes": self.message.deadline_minutes,
            "xml": self.xml,
        }


def _utc(value: Any, label: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise DayZMessagesError(f"invalid {label}") from exc
    if parsed.tzinfo is None:
        raise DayZMessagesError(f"{label} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def deadline_minutes_for_due(due_at: Any, *, now: Any | None = None) -> int:
    """Return DayZ countdown minutes for a stopped instance about to start.

    ``messages.xml`` is treated as startup configuration.  The caller must
    materialize it while the instance is stopped and start the server immediately
    afterwards.  Rounding up prevents an early shutdown caused by sub-minute
    Controller/Agent transport or lifecycle delay.
    """
    due = _utc(due_at, "due_at")
    current = _utc(now if now is not None else datetime.now(timezone.utc), "now")
    remaining = (due - current).total_seconds()
    if remaining <= 0:
        raise DayZMessagesError("DayZ native restart due_at must be in the future")
    minutes = max(1, int(math.ceil(remaining / 60.0)))
    if minutes > 10080:
        raise DayZMessagesError("DayZ native restart due_at exceeds the 7 day countdown limit")
    return minutes


def _runtime_root(record: dict[str, Any]) -> Path:
    value = str(record.get("working_directory") or record.get("path") or "").strip()
    if not value:
        raise DayZMessagesError("DayZ runtime has no working_directory")
    root = Path(value)
    if not root.is_absolute():
        raise DayZMessagesError("DayZ working_directory must be absolute")
    return root.resolve()


def _inside(root: Path, candidate: Path, label: str) -> Path:
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise DayZMessagesError(f"{label} is outside instance root") from exc
    return resolved


def _instance_state_root(record: dict[str, Any]) -> Path | None:
    for key in ("instance_state_root", "files_root"):
        value = str(record.get(key) or "").strip()
        if not value:
            continue
        root = Path(value)
        if not root.is_absolute():
            raise DayZMessagesError(f"DayZ {key} must be absolute")
        return root.resolve()
    return None


def _inside_trusted_roots(
    record: dict[str, Any],
    candidate: Path,
    label: str,
) -> Path:
    roots = [_runtime_root(record)]
    state_root = _instance_state_root(record)
    if state_root is not None and state_root not in roots:
        roots.append(state_root)
    resolved = candidate.resolve()
    for root in roots:
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue
    raise DayZMessagesError(f"{label} is outside instance roots")


def _argument(record: dict[str, Any], pattern: re.Pattern[str]) -> str | None:
    values = record.get("arguments")
    if not isinstance(values, list):
        return None
    for raw in values:
        match = pattern.match(str(raw or "").strip())
        if match:
            value = match.group(1).strip().strip("\"'")
            return value or None
    return None


def resolve_dayz_mission(record: dict[str, Any]) -> tuple[str, Path]:
    if str(record.get("game_id") or "").strip().lower() != "dayz":
        raise DayZMessagesError("native DayZ restart requires game_id=dayz")
    root = _runtime_root(record)
    state_root = _instance_state_root(record)
    mission_value = _argument(record, _MISSION_ARG)
    if mission_value:
        raw = Path(mission_value)
        candidate = raw if raw.is_absolute() else root / raw
        mission_root = _inside_trusted_roots(
            record,
            candidate,
            "DayZ mission path",
        )
        mission = mission_root.name
    else:
        config_value = _argument(record, _CONFIG_ARG) or "serverDZ.cfg"
        config_path = Path(config_value)
        if not config_path.is_absolute():
            config_path = root / config_path
        config_path = _inside_trusted_roots(
            record,
            config_path,
            "DayZ server config",
        )
        try:
            source = config_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise DayZMessagesError(f"cannot read DayZ server config: {exc}") from exc
        match = _TEMPLATE.search(source)
        if not match:
            raise DayZMessagesError("DayZ mission template not found in server config")
        mission = match.group(1).strip()
        mission_base = state_root if state_root is not None else root
        mission_root = _inside_trusted_roots(
            record,
            mission_base / "mpmissions" / mission,
            "DayZ mission path",
        )
    if not _SAFE_MISSION.fullmatch(mission):
        raise DayZMessagesError("invalid DayZ mission name")
    return mission, mission_root


def _new_message(message: DayZShutdownMessage) -> ET.Element:
    message.validate()
    item = ET.Element("message")
    for tag, value in (
        ("delay", "0"),
        ("repeat", "0"),
        ("deadline", str(message.deadline_minutes)),
        ("onConnect", "0"),
        ("shutdown", "1"),
        ("text", message.text.strip()),
    ):
        ET.SubElement(item, tag).text = value
    return item


def render_shutdown_messages_xml(message: DayZShutdownMessage, *, existing_xml: str | None = None) -> str:
    message.validate()
    if existing_xml and existing_xml.strip():
        try:
            root = ET.fromstring(existing_xml)
        except ET.ParseError as exc:
            raise DayZMessagesError("existing messages.xml is invalid") from exc
        if root.tag != "messages":
            raise DayZMessagesError("existing messages.xml root must be <messages>")
    else:
        root = ET.Element("messages")
    for node in list(root.findall("message")):
        text = str(node.findtext("text") or "").strip()
        shutdown = str(node.findtext("shutdown") or "0").strip()
        if text == MANAGED_TEXT or shutdown == "1":
            root.remove(node)
    root.append(_new_message(message))
    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode", short_empty_elements=False)
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + body + "\n"


def native_restart_plan(record: dict[str, Any], deadline_minutes: int, *, existing_xml: str | None = None) -> DayZNativeRestartPlan:
    instance_id = str(record.get("instance_id") or "").strip()
    if not instance_id:
        raise DayZMessagesError("instance_id is required")
    mission, mission_root = resolve_dayz_mission(record)
    target = _inside_trusted_roots(
        record,
        mission_root / "db" / "messages.xml",
        "DayZ messages.xml",
    )
    message = DayZShutdownMessage(int(deadline_minutes))
    return DayZNativeRestartPlan(
        instance_id=instance_id,
        mission=mission,
        messages_path=str(target),
        message=message,
        xml=render_shutdown_messages_xml(message, existing_xml=existing_xml),
    )


def materialize_shutdown_messages_xml(path: Path, message: DayZShutdownMessage, *, existing_xml: str | None = None) -> Path:
    target = Path(path)
    if target.name.lower() != "messages.xml":
        raise DayZMessagesError("target must be messages.xml")
    target.parent.mkdir(parents=True, exist_ok=True)
    current = existing_xml
    if current is None and target.exists():
        try:
            current = target.read_text(encoding="utf-8")
        except OSError as exc:
            raise DayZMessagesError(f"cannot read existing messages.xml: {exc}") from exc
    payload = render_shutdown_messages_xml(message, existing_xml=current)
    mode = target.stat().st_mode & 0o777 if target.exists() else 0o640
    owner = None
    if target.exists() and hasattr(os, "chown"):
        stat = target.stat()
        owner = (stat.st_uid, stat.st_gid)
    with NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, prefix=".messages.xml.", delete=False) as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    try:
        os.chmod(temporary, mode)
        if owner is not None:
            try:
                os.chown(temporary, owner[0], owner[1])
            except PermissionError:
                # Hybrid workers commonly have group-write access to the
                # instance file but cannot chown an atomic replacement back to
                # the instance runtime identity.  Preserve the existing inode
                # ownership instead of silently replacing it with the worker.
                temporary.unlink()
                with target.open("w", encoding="utf-8") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                # The existing inode already has the intended mode and
                # ownership. A group-authorized Hybrid worker may write it but
                # cannot chmod/chown it because it is not the inode owner.
                return target
        temporary.replace(target)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return target


__all__ = [
    "DayZMessagesError",
    "DayZNativeRestartPlan",
    "DayZShutdownMessage",
    "MANAGED_TEXT",
    "deadline_minutes_for_due",
    "materialize_shutdown_messages_xml",
    "native_restart_plan",
    "render_shutdown_messages_xml",
    "resolve_dayz_mission",
]
