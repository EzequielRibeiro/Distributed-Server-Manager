#!/usr/bin/env python3
"""Recover an existing Windows Agent credential with a one-time Controller token."""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

PROGRAM_DATA = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
CONFIG_PATH = Path(os.environ.get("CAPIVARA_AGENT_CONFIG", PROGRAM_DATA / "CapivaraAgent" / "agent.json"))


def _load() -> dict:
    value = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("Agent config must be a JSON object")
    return value


def _post(url: str, payload: dict) -> dict:
    request = urllib.request.Request(url, data=json.dumps(payload, separators=(",", ":")).encode("utf-8"), headers={"Content-Type": "application/json", "Accept": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Controller rejected relink ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Controller unavailable: {exc.reason}") from exc
    if not isinstance(result, dict):
        raise RuntimeError("invalid Controller relink response")
    return result


def relink(token: str) -> dict:
    config = _load()
    required = ("controller_url", "agent_id", "node_id", "fingerprint")
    missing = [key for key in required if not str(config.get(key) or "").strip()]
    if missing:
        raise RuntimeError("Agent identity is incomplete: " + ", ".join(missing))
    result = _post(str(config["controller_url"]).rstrip("/") + "/api/agent/relink", {"pairing_token": str(token).strip(), "agent_id": config["agent_id"], "node_id": config["node_id"], "fingerprint": config["fingerprint"]})
    config.update({"controller_id": result["controller_id"], "credential_id": result["credential_id"], "credential_secret": result["credential_secret"], "credential_type": result.get("credential_type", "opaque-v1")})
    config.pop("pairing_token", None)
    temp = CONFIG_PATH.with_suffix(".relink.tmp")
    temp.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(CONFIG_PATH)
    return {"agent_id": result["agent_id"], "node_id": result["node_id"], "controller_id": result["controller_id"], "credential_id": result["credential_id"], "status": result.get("status", "pairing"), "config_path": str(CONFIG_PATH)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely relink an existing Capivara Windows Agent")
    parser.add_argument("--token", required=True)
    args = parser.parse_args()
    try:
        result = relink(args.token)
    except Exception as exc:
        print(f"RELINK_FAILED: {exc}")
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("RELINK_OK: restart the Capivara Agent service and wait for heartbeat")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
