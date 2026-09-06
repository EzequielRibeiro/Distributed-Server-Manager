#!/usr/bin/env python3
"""Regression contract for explicit Minecraft Java EULA acceptance."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    backend_path = ROOT / "dashboard" / "customer_instance_creation.py"
    wizard_path = ROOT / "dashboard" / "web" / "create-server-wizard.js"
    customer_path = ROOT / "dashboard" / "web" / "customer.html"

    backend = backend_path.read_text(encoding="utf-8")
    wizard = wizard_path.read_text(encoding="utf-8")
    customer = customer_path.read_text(encoding="utf-8")

    ast.parse(backend, filename=str(backend_path))

    require('id="minecraft-eula-accepted"' in customer, "customer wizard must expose explicit Minecraft EULA checkbox")
    require("Minecraft EULA" in customer, "customer wizard must label the Minecraft EULA acceptance")
    require("payload.minecraft_eula_accepted=eulaAccepted()" in wizard, "create wizard must transport EULA acceptance")
    require("requiresMinecraftJavaEula()&&!eulaAccepted()" in wizard, "submit must remain blocked until Java EULA acceptance")
    require('runtime_edition=str(runtime_def.get("edition")' in backend, "backend must derive edition from RuntimeDefinition")
    require('game=="minecraft" and runtime_edition=="java"' in backend, "backend must scope EULA validation to Minecraft Java")
    require('payload.get("minecraft_eula_accepted") is not True' in backend, "backend must reject missing or non-boolean EULA acceptance")
    require("Minecraft Java EULA acceptance is required" in backend, "backend must expose deterministic validation error")
    require("minecraft_eula=accepted" in backend, "accepted EULA must be represented in the creation audit trail")

    print("Minecraft Java customer EULA contract tests passed.")


if __name__ == "__main__":
    main()
