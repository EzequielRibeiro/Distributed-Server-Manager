#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "release" / "build_release.sh"
PATCHER = ROOT / "release" / "legacy_updater_bridge.py"


def run(*args: str) -> None:
    subprocess.run(list(args), cwd=ROOT, check=True)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="capivara-bridge-test-") as temp:
        dist = Path(temp) / "dist"
        run("bash", str(BUILDER), "HEAD", str(dist))
        version = (ROOT / "version").read_text(encoding="utf-8").strip()
        archive = dist / f"capivara-dsm-{version}.tar.gz"
        run("python3", str(PATCHER), str(archive))

        checksum = archive.with_name(archive.name + ".sha256")
        checksum_hash, checksum_name = checksum.read_text(encoding="utf-8").split()
        assert checksum_name == archive.name
        assert checksum_hash == hashlib.sha256(archive.read_bytes()).hexdigest()

        extract = Path(temp) / "extract"
        extract.mkdir()
        with tarfile.open(archive, "r:gz") as package:
            package.extractall(extract)
        package_root = extract / f"capivara-dsm-{version}"
        bridge = package_root / "bin" / "dsm"
        compat = package_root / "bin" / "dsm-compat"
        update = package_root / "update.sh"
        assert not (ROOT / "bin" / "dsm").exists(), "source tree must remain cap-only"
        assert bridge.is_file(), "package-only legacy updater bridge is missing"
        assert not os.access(bridge, os.X_OK), "legacy updater bridge must not be executable"
        assert bridge.read_text(encoding="utf-8").splitlines()[0] == "CAPIVARA_RELEASE_UPDATER_BRIDGE_ONLY"
        assert not compat.exists(), "retired dsm-compat implementation must not be packaged"

        update_text = update.read_text(encoding="utf-8")
        assert 'rm -f -- "${INSTALL_DIR}/bin/dsm" "${INSTALL_DIR}/bin/dsm-compat"' in update_text
        assert '"${INSTALL_DIR}/bin/dsm"\n        "${INSTALL_DIR}/bin/cap"' not in update_text
        assert "Retired CLI artifact remained after update" in update_text
        run("bash", "-n", str(update))

        # Reproduce the exact path-level contract enforced by the v2.0.46 verifier.
        for relative in ("version", "bin/dsm", "core/bootstrap.sh"):
            assert (package_root / relative).exists(), f"v2.0.46 verifier requirement missing: {relative}"

        internal_manifest = package_root / "release-manifest.json"
        external_manifest = dist / f"capivara-dsm-{version}.manifest.json"
        assert internal_manifest.read_bytes() == external_manifest.read_bytes()
        manifest = json.loads(internal_manifest.read_text(encoding="utf-8"))
        actual_count = sum(1 for item in package_root.rglob("*") if item.is_file() and not item.is_symlink())
        assert manifest["file_count"] == actual_count
        assert "bin/dsm" not in manifest["required_files"], "bridge must not become a product requirement"

    print("Legacy updater cap-only bridge test passed.")


if __name__ == "__main__":
    main()
