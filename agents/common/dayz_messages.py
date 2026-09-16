#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from xml.etree import ElementTree as ET


class DayZMessagesError(ValueError):
    pass


@dataclass(frozen=True)
class DayZShutdownMessage:
    deadline_minutes: int
    text: str = "#name will shutdown in #tmin minutes."

    def validate(self) -> None:
        if not isinstance(self.deadline_minutes, int) or isinstance(self.deadline_minutes, bool):
            raise DayZMessagesError("deadline_minutes must be an integer")
        if self.deadline_minutes < 1 or self.deadline_minutes > 10080:
            raise DayZMessagesError("deadline_minutes must be between 1 and 10080")
        text = str(self.text or "").strip()
        if not text:
            raise DayZMessagesError("text must not be empty")
        if len(text) > 512:
            raise DayZMessagesError("text must be at most 512 characters")
        if "\x00" in text:
            raise DayZMessagesError("text contains NUL")


def render_shutdown_messages_xml(message: DayZShutdownMessage) -> str:
    message.validate()
    root = ET.Element("messages")
    item = ET.SubElement(root, "message")
    ET.SubElement(item, "deadline").text = str(message.deadline_minutes)
    ET.SubElement(item, "shutdown").text = "1"
    ET.SubElement(item, "text").text = message.text.strip()
    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode", short_empty_elements=False)
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + body + "\n"


def materialize_shutdown_messages_xml(path: Path, message: DayZShutdownMessage) -> Path:
    target = Path(path)
    if target.name.lower() != "messages.xml":
        raise DayZMessagesError("target must be messages.xml")
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = render_shutdown_messages_xml(message)
    with NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, prefix=".messages.xml.", delete=False) as handle:
        handle.write(payload)
        handle.flush()
        temporary = Path(handle.name)
    temporary.replace(target)
    return target
