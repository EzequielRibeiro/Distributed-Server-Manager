#!/usr/bin/env python3
"""Write a private minimal Arma Reforger dedicated-server JSON configuration."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile

_SCENARIO = "{ECC61978EDCC2B5A}Missions/23_Campaign.conf"


def _load_existing(path: Path) -> dict:
    if not path.exists():
        return {}
    if not path.is_file() or path.is_symlink():
        raise ValueError("Arma Reforger config path must be a regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Arma Reforger existing config is invalid") from exc
    if not isinstance(value, dict):
        raise ValueError("Arma Reforger existing config must be an object")
    return value

def prepare(config_path: str, game_port: int, query_port: int, name: str) -> None:
    path = Path(config_path)
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("Arma Reforger config path must be an absolute regular path")
    game_port, query_port = int(game_port), int(query_port)
    if not (1 <= game_port <= 65535 and 1 <= query_port <= 65535 and game_port != query_port):
        raise ValueError("invalid Arma Reforger reserved ports")
    payload = _load_existing(path)
    payload["bindPort"] = game_port
    payload["publicPort"] = game_port
    a2s = payload.setdefault("a2s", {})
    if not isinstance(a2s, dict): raise ValueError("Arma Reforger a2s config is invalid")
    a2s["port"] = query_port
    game = payload.setdefault("game", {})
    if not isinstance(game, dict): raise ValueError("Arma Reforger game config is invalid")
    game.setdefault("name", str(name or "Capivara Reforger")[:128])
    game.setdefault("password", "")
    game.setdefault("passwordAdmin", "")
    game.setdefault("admins", [])
    game.setdefault("scenarioId", _SCENARIO)
    game.setdefault("maxPlayers", 32)
    game.setdefault("visible", True)
    properties = game.setdefault("gameProperties", {})
    if not isinstance(properties, dict): raise ValueError("Arma Reforger gameProperties is invalid")
    defaults = {
        "serverMaxViewDistance": 1600, "serverMinGrassDistance": 0,
        "networkViewDistance": 1500, "disableThirdPerson": False,
        "fastValidation": True, "battlEye": True, "VONDisableUI": False,
        "VONDisableDirectSpeechUI": False, "VONCanTransmitCrossFaction": False,
    }
    for key, value in defaults.items(): properties.setdefault(key, value)
    game.setdefault("mods", [])
    operating = payload.setdefault("operating", {})
    if not isinstance(operating, dict): raise ValueError("Arma Reforger operating config is invalid")
    join_queue = operating.setdefault("joinQueue", {})
    if not isinstance(join_queue, dict): raise ValueError("Arma Reforger joinQueue config is invalid")
    join_queue.setdefault("maxSize", 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".armareforger.", suffix=".json", dir=str(path.parent))
    os.close(fd)
    temp = Path(temporary)
    try:
        temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    finally:
        try: temp.unlink()
        except FileNotFoundError: pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--game-port", type=int, required=True)
    parser.add_argument("--query-port", type=int, required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    prepare(args.config, args.game_port, args.query_port, args.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
