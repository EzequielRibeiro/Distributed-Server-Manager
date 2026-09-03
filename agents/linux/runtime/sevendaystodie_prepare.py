#!/usr/bin/env python3
"""Prepare private 7 Days to Die XML configuration without shell execution."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET


def prepare(config_path: str, port: int) -> None:
    path = Path(config_path)
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("7 Days to Die config path must be an absolute regular path")
    port = int(port)
    if not 1 <= port <= 65532:
        raise ValueError("invalid 7 Days to Die game port")
    if not path.is_file():
        raise RuntimeError("7 Days to Die private serverconfig.xml is unavailable")
    tree = ET.parse(path)
    root = tree.getroot()
    target = None
    for item in root.findall(".//property"):
        if str(item.attrib.get("name") or "") == "ServerPort":
            target = item
            break
    if target is None:
        target = ET.SubElement(root, "property")
        target.set("name", "ServerPort")
    target.set("value", str(port))
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".serverconfig.", suffix=".xml", dir=str(path.parent))
    os.close(fd)
    temp = Path(temporary)
    try:
        tree.write(temp, encoding="utf-8", xml_declaration=True)
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    prepare(args.config, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
