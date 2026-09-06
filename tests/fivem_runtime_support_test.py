#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
sys.path.insert(0, str(RUNTIME))

from fivem_install import resolve_recommended_artifact
from profiles.fivem import FiveMRuntimeProfile


def test_resolve_recommended_artifact_uses_official_linux_asset():
    document = '''<html><body><a href="35245-deadbeef/fx.tar.xz">LATEST RECOMMENDED (35245)</a></body></html>'''
    assert resolve_recommended_artifact(document) == (
        "https://runtime.fivem.net/artifacts/fivem/build_proot_linux/master/"
        "35245-deadbeef/fx.tar.xz"
    )


def test_fivem_profile_uses_credential_not_plaintext_license():
    instance = {
        "instance_id": "instance-1",
        "agent_id": "agent-1",
        "game_id": "fivem",
        "environment_id": "fivem.stable",
    }
    context = {
        "install_path": "/opt/dsm/game-data/fivem/serverfiles",
        "instance_state_root": "/var/lib/capivara-instances/instance-1",
        "catalog_runtime_policy": {"runtime_id": "fivem.stable"},
        "ports": {"game": {"port": 30120, "protocol": "udp"}},
    }
    spec = FiveMRuntimeProfile().build_runtime_spec(instance, context)
    assert spec["profile"] == "fivem"
    assert spec["secret_refs"] == [{
        "name": "FIVEM_LICENSE_KEY",
        "ref": "instance/instance-1/FIVEM_LICENSE_KEY",
        "target": "file",
    }]
    rendered = repr(spec)
    assert "sv_licenseKey" not in rendered
    assert "/server/run.sh" in rendered
    assert "/server-data" in rendered


def test_fivem_catalog_is_active_not_deferred():
    active = ROOT / "catalog" / "v2" / "games" / "fivem" / "runtimes" / "stable.json"
    deferred = ROOT / "catalog" / "v2" / "games" / "fivem" / "deferred" / "stable.json"
    assert active.is_file()
    assert not deferred.exists()


def test_fivem_uses_typed_executable_provider():
    runtime = json.loads((ROOT / "catalog" / "v2" / "games" / "fivem" / "runtimes" / "stable.json").read_text())
    providers = json.loads((ROOT / "catalog" / "v2" / "providers" / "catalog-providers.json").read_text())
    assert runtime["artifact"]["provider"] == "fivem"
    assert "fivem" in providers["agent_executable_artifact_providers"]
    assert "fivem" not in providers["reserved_artifact_providers"]
