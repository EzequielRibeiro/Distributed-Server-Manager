#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from runtime_spec import RuntimeSpecError, validate_runtime_spec
from profiles.palworld import PalworldRuntimeProfile


def _load_materializer_module():
    previous = os.environ.get("CAPIVARA_AGENT_ROOT")
    os.environ["CAPIVARA_AGENT_ROOT"] = str(ROOT / "agents" / "linux")
    try:
        path = ROOT / "agents" / "linux" / "privileged" / "materialize_instance.py"
        spec = importlib.util.spec_from_file_location("palworld_optional_seed_materializer", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if previous is None:
            os.environ.pop("CAPIVARA_AGENT_ROOT", None)
        else:
            os.environ["CAPIVARA_AGENT_ROOT"] = previous


class PalworldOptionalSeedTest(unittest.TestCase):
    def _base_spec(self) -> dict:
        return {
            "instance_id": "palworld-test",
            "agent_id": "agent-test",
            "runtime_id": "palworld-test",
            "adapter": "systemd",
            "working_directory": "/srv/palworld",
            "executable": "/srv/palworld/PalServer.sh",
            "instance_state_root": "/var/lib/capivara-instances/palworld-test",
            "seed_directories": [
                {
                    "source": "/srv/palworld/Pal/Saved",
                    "target": "/var/lib/capivara-instances/palworld-test/Pal/Saved",
                    "optional": True,
                }
            ],
            "working_file_copies": [
                {
                    "source": "/srv/palworld/linux64/steamclient.so",
                    "target": "/srv/palworld/Pal/Binaries/Linux/steamclient.so",
                }
            ],
        }

    def test_runtime_spec_preserves_explicit_optional_seed_directory(self) -> None:
        result = validate_runtime_spec(self._base_spec(), expected_agent_id="agent-test")
        self.assertEqual(result["seed_directories"][0]["optional"], True)

    def test_runtime_spec_preserves_working_file_copy(self) -> None:
        result = validate_runtime_spec(self._base_spec(), expected_agent_id="agent-test")
        self.assertEqual(
            result["working_file_copies"],
            [{
                "source": "/srv/palworld/linux64/steamclient.so",
                "target": "/srv/palworld/Pal/Binaries/Linux/steamclient.so",
            }],
        )

    def test_runtime_spec_rejects_non_boolean_optional_seed_directory(self) -> None:
        spec = self._base_spec()
        spec["seed_directories"][0]["optional"] = "true"
        with self.assertRaises(RuntimeSpecError):
            validate_runtime_spec(spec)

    def test_palworld_profile_marks_saved_seed_optional_and_bootstraps_steamclient(self) -> None:
        runtime = PalworldRuntimeProfile().build_runtime_spec(
            {"instance_id": "palworld-test", "agent_id": "agent-test", "environment_id": "palworld.stable"},
            {
                "install_path": "/srv/palworld",
                "instance_state_root": "/var/lib/capivara-instances/palworld-test",
                "catalog_runtime_policy": {"runtime_id": "palworld.stable", "executable": "PalServer.sh"},
                "ports": {"game": {"port": 8211, "protocol": "udp"}},
            },
        )
        self.assertEqual(runtime["profile_version"], 2)
        self.assertEqual(runtime["seed_directories"], [
            {
                "source": "/srv/palworld/Pal/Saved",
                "target": "/var/lib/capivara-instances/palworld-test/Pal/Saved",
                "optional": True,
            }
        ])
        self.assertEqual(runtime["working_file_copies"], [
            {
                "source": "/srv/palworld/linux64/steamclient.so",
                "target": "/srv/palworld/Pal/Binaries/Linux/steamclient.so",
            }
        ])

    def test_missing_optional_directory_seed_is_a_noop(self) -> None:
        module = _load_materializer_module()
        account = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "private" / "Saved"
            module._seed_directory(root / "missing", target, account, optional=True)
            self.assertFalse(target.exists())

    def test_missing_required_directory_seed_still_fails(self) -> None:
        module = _load_materializer_module()
        account = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(RuntimeError, "seed directory source is unavailable"):
                module._seed_directory(root / "missing", root / "private" / "Saved", account)

    def test_working_file_copy_is_idempotent_and_refreshes_changed_source(self) -> None:
        module = _load_materializer_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "linux64" / "steamclient.so"
            target = root / "Pal" / "Binaries" / "Linux" / "steamclient.so"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"steamclient-v1")
            spec = {
                "working_directory": str(root),
                "working_file_copies": [{"source": str(source), "target": str(target)}],
            }

            first = module._sync_working_file_copies(spec)
            self.assertTrue(first[0]["changed"])
            self.assertEqual(target.read_bytes(), b"steamclient-v1")

            second = module._sync_working_file_copies(spec)
            self.assertFalse(second[0]["changed"])

            source.write_bytes(b"steamclient-v2")
            third = module._sync_working_file_copies(spec)
            self.assertTrue(third[0]["changed"])
            self.assertEqual(target.read_bytes(), b"steamclient-v2")

    def test_working_file_copy_rejects_target_escape(self) -> None:
        module = _load_materializer_module()
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            source = root / "linux64" / "steamclient.so"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"steamclient")
            spec = {
                "working_directory": str(root),
                "working_file_copies": [{"source": str(source), "target": str(Path(outside) / "steamclient.so")}],
            }
            with self.assertRaisesRegex(RuntimeError, "escapes its allowed root"):
                module._sync_working_file_copies(spec)


if __name__ == "__main__":
    unittest.main()