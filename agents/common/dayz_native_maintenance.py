#!/usr/bin/env python3
"""Pure DayZ native-maintenance planner used by Linux and Windows Agents.

The Controller never supplies filesystem paths or XML. The Agent derives the
mission from its already materialized RuntimeSpec and produces a bounded plan
that a privileged writer can apply atomically.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any
import xml.etree.ElementTree as ET

_CONFIG_ARG = re.compile(r"^-config=(.+)$", re.IGNORECASE)
_MISSION_ARG = re.compile(r"^-mission=(.+)$", re.IGNORECASE)
_TEMPLATE = re.compile(r"\btemplate\s*=\s*[\"']([^\"']+)[\"']\s*;", re.IGNORECASE)
_SAFE_MISSION = re.compile(r"^[A-Za-z0-9._-]{1,191}$")
MANAGED_TEXT = "Capivara maintenance: #name will restart in #tmin minutes."


class DayZNativeMaintenanceError(ValueError):
    pass


@dataclass(frozen=True)
class DayZNativeMaintenancePlan:
    instance_id: str
    mission: str
    messages_path: str
    deadline_minutes: int
    xml: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "CapivaraDayZNativeMaintenancePlan",
            "instance_id": self.instance_id,
            "mission": self.mission,
            "messages_path": self.messages_path,
            "deadline_minutes": self.deadline_minutes,
            "xml": self.xml,
        }


def _root(record: dict[str, Any]) -> Path:
    value = str(record.get("working_directory") or record.get("path") or "").strip()
    if not value:
        raise DayZNativeMaintenanceError("DayZ runtime has no working_directory")
    root = Path(value)
    if not root.is_absolute():
        raise DayZNativeMaintenanceError("DayZ working_directory must be absolute")
    return root.resolve()


def _inside(root: Path, candidate: Path, label: str) -> Path:
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise DayZNativeMaintenanceError(f"{label} is outside instance root") from exc
    return resolved


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


def _mission_from_argument(root: Path, value: str) -> tuple[str, Path]:
    raw = Path(value)
    mission_root = raw if raw.is_absolute() else root / raw
    mission_root = _inside(root, mission_root, "DayZ mission path")
    name = mission_root.name
    if not _SAFE_MISSION.fullmatch(name):
        raise DayZNativeMaintenanceError("invalid DayZ mission name")
    return name, mission_root


def _mission_from_config(root: Path, record: dict[str, Any]) -> tuple[str, Path]:
    config_value = _argument(record, _CONFIG_ARG) or "serverDZ.cfg"
    config_path = Path(config_value)
    if not config_path.is_absolute():
        config_path = root / config_path
    config_path = _inside(root, config_path, "DayZ server config")
    try:
        source = config_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise DayZNativeMaintenanceError(f"cannot read DayZ server config: {exc}") from exc
    match = _TEMPLATE.search(source)
    if not match:
        raise DayZNativeMaintenanceError("DayZ mission template not found in server config")
    mission = match.group(1).strip()
    if not _SAFE_MISSION.fullmatch(mission):
        raise DayZNativeMaintenanceError("invalid DayZ mission template")
    return mission, _inside(root, root / "mpmissions" / mission, "DayZ mission path")


def resolve_mission(record: dict[str, Any]) -> tuple[str, Path]:
    if str(record.get("game_id") or "").strip().lower() != "dayz":
        raise DayZNativeMaintenanceError("native DayZ maintenance requires game_id=dayz")
    root = _root(record)
    mission_arg = _argument(record, _MISSION_ARG)
    if mission_arg:
        return _mission_from_argument(root, mission_arg)
    return _mission_from_config(root, record)


def _managed_message(deadline_minutes: int) -> ET.Element:
    message = ET.Element("message")
    for tag, value in (
        ("delay", "0"),
        ("repeat", "0"),
        ("deadline", str(deadline_minutes)),
        ("onConnect", "0"),
        ("shutdown", "1"),
        ("text", MANAGED_TEXT),
    ):
        child = ET.SubElement(message, tag)
        child.text = value
    return message


def render_messages_xml(existing: str | None, deadline_minutes: int) -> str:
    try:
        deadline = int(deadline_minutes)
    except (TypeError, ValueError) as exc:
        raise DayZNativeMaintenanceError("invalid DayZ native countdown deadline") from exc
    if deadline < 1 or deadline > 10080:
        raise DayZNativeMaintenanceError("DayZ native countdown deadline must be between 1 and 10080 minutes")
    if existing and existing.strip():
        try:
            root = ET.fromstring(existing)
        except ET.ParseError as exc:
            raise DayZNativeMaintenanceError("existing DayZ messages.xml is invalid") from exc
        if root.tag != "messages":
            raise DayZNativeMaintenanceError("existing DayZ messages.xml root must be <messages>")
    else:
        root = ET.Element("messages")
    for node in list(root.findall("message")):
        text = node.find("text")
        if text is not None and str(text.text or "").strip() == MANAGED_TEXT:
            root.remove(node)
    root.append(_managed_message(deadline))
    ET.indent(root, space="\t")
    body = ET.tostring(root, encoding="unicode", short_empty_elements=False)
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + body + "\n"


def plan(record: dict[str, Any], deadline_minutes: int, *, existing_xml: str | None = None) -> DayZNativeMaintenancePlan:
    instance_id = str(record.get("instance_id") or "").strip()
    if not instance_id:
        raise DayZNativeMaintenanceError("instance_id is required")
    mission, mission_root = resolve_mission(record)
    root = _root(record)
    messages_path = _inside(root, mission_root / "db" / "messages.xml", "DayZ messages.xml")
    xml = render_messages_xml(existing_xml, deadline_minutes)
    return DayZNativeMaintenancePlan(
        instance_id=instance_id,
        mission=mission,
        messages_path=str(messages_path),
        deadline_minutes=int(deadline_minutes),
        xml=xml,
    )


__all__ = [
    "DayZNativeMaintenanceError",
    "DayZNativeMaintenancePlan",
    "MANAGED_TEXT",
    "plan",
    "render_messages_xml",
    "resolve_mission",
]
