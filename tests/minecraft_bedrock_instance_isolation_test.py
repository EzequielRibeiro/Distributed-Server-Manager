#!/usr/bin/env python3
"""Regression coverage for Minecraft Bedrock private runtime state."""
from __future__ import annotations

import importlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "agents" / "linux" / "runtime", ROOT / "dashboard"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from dashboard.catalog_controller_runtime_policy import default_policy
from agents.linux.runtime.catalog_runtime_policy import apply_policy, materialize_network_properties
from agents.linux.runtime.profiles.minecraft_bedrock import MinecraftBedrockRuntimeProfile
from agents.linux.runtime.profiles.minecraft_java import MinecraftJavaRuntimeProfile
from agents.linux.runtime.profiles.base import ProfileError

RUNTIME_ID = "minecraft.bedrock.vanilla"


def require(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def runtime_definition() -> dict:
    path = ROOT / "catalog" / "v2" / "games" / "minecraft" / "runtimes" / "bedrock-vanilla.json"
    return json.loads(path.read_text(encoding="utf-8"))


def build(profile: MinecraftBedrockRuntimeProfile, install: Path, state: Path, instance_id: str, first: int) -> dict:
    runtime = runtime_definition()
    policy = default_policy(runtime)
    context = {
        "install_path": str(install),
        "content_root": str(install),
        "instance_state_root": str(state),
        "catalog_runtime_policy": policy,
        "ports": {
            "game_ipv4": {"port": first, "protocol": "udp"},
            "game_ipv6": {"port": first + 1, "protocol": "udp"},
        },
    }
    instance = {
        "instance_id": instance_id,
        "agent_id": "agent-test",
        "game_id": "minecraft",
        "environment_id": RUNTIME_ID,
        "runtime_id": instance_id,
    }
    spec = profile.build_runtime_spec(instance, context)
    return apply_policy(spec, instance, context)


def main() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        install = root / "game-data" / "minecraft" / "bedrock"
        install.mkdir(parents=True)
        (install / "bedrock_server").write_text("binary", encoding="utf-8")
        (install / "server.properties").write_text("server-port=19132\nserver-portv6=19133\nlevel-name=Bedrock level\n", encoding="utf-8")
        (install / "worlds").mkdir()
        (install / "worlds" / "provider-seed.txt").write_text("seed", encoding="utf-8")

        profile = MinecraftBedrockRuntimeProfile()
        a = build(profile, install, root / "instances" / "bedrock-a", "bedrock-a", 22000)
        b = build(profile, install, root / "instances" / "bedrock-b", "bedrock-b", 23000)

        require(a["working_directory"] != b["working_directory"], "instances must use disjoint private working trees")
        require(a["configuration_root"] != b["configuration_root"], "instances must use disjoint configuration roots")
        require(a["seed_directories"][0]["source"] == b["seed_directories"][0]["source"], "instances should share the immutable provider seed")
        require(a["seed_directories"][0]["target"] != b["seed_directories"][0]["target"], "provider seed targets must be private")
        require(a["environment"]["LD_LIBRARY_PATH"] == a["working_directory"], "Bedrock libraries must resolve from private runtime")
        require(b["environment"]["LD_LIBRARY_PATH"] == b["working_directory"], "Bedrock libraries must resolve from private runtime")
        require(a["ports"]["game_ipv4"]["port"] == 22000 and a["ports"]["game_ipv6"]["port"] == 22001, "instance A port block is wrong")
        require(b["ports"]["game_ipv4"]["port"] == 23000 and b["ports"]["game_ipv6"]["port"] == 23001, "instance B port block is wrong")

        # Simulate the copy-once seed boundary, then prove network policy edits private files only.
        import shutil
        shutil.copytree(install, Path(a["working_directory"]))
        shutil.copytree(install, Path(b["working_directory"]))
        materialize_network_properties(a)
        materialize_network_properties(b)
        a_props = (Path(a["working_directory"]) / "server.properties").read_text(encoding="utf-8")
        b_props = (Path(b["working_directory"]) / "server.properties").read_text(encoding="utf-8")
        shared_props = (install / "server.properties").read_text(encoding="utf-8")
        require("server-port=22000" in a_props and "server-portv6=22001" in a_props, "instance A private ports were not materialized")
        require("server-port=23000" in b_props and "server-portv6=23001" in b_props, "instance B private ports were not materialized")
        require("server-port=19132" in shared_props and "server-portv6=19133" in shared_props, "provider seed must remain unchanged")

        registry = importlib.import_module("agents.linux.runtime.profiles.registry")
        resolved = registry.resolve_profile({"game_id": "minecraft", "environment_id": RUNTIME_ID})
        require(isinstance(resolved, MinecraftBedrockRuntimeProfile), "Linux registry must route Bedrock to dedicated profile")
        try:
            MinecraftJavaRuntimeProfile().build_runtime_spec(
                {"instance_id": "bad", "agent_id": "agent-test", "environment_id": RUNTIME_ID},
                {"install_path": str(install), "instance_state_root": str(root / "bad"), "ports": {"game": {"port": 25565, "protocol": "tcp"}}, "catalog_runtime_policy": {"runtime_id": RUNTIME_ID}},
            )
        except ProfileError:
            pass
        else:
            raise AssertionError("Minecraft Java profile must reject Bedrock")

    print("Minecraft Bedrock instance isolation tests passed.")


if __name__ == "__main__":
    main()
