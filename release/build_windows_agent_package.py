#!/usr/bin/env python3
"""Build a reproducible Windows Agent ZIP package from one Git commit."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def git_text(*args: str) -> str:
    return git(*args).decode("utf-8").strip()


def git_file(ref: str, path: str) -> bytes:
    return git("show", f"{ref}:{path}")


def main() -> int:
    ref = sys.argv[1] if len(sys.argv) > 1 else "HEAD"
    output_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "dist"
    commit = git_text("rev-parse", f"{ref}^{{commit}}")
    version = git_text("show", f"{ref}:version")
    channel = "beta" if "-" in version else "stable"
    package_name = f"capivara-agent-windows-{version}"
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"{package_name}.zip"
    checksum = output_dir / f"{package_name}.zip.sha256"
    external_manifest = output_dir / f"{package_name}.manifest.json"

    sources = {
        "install-agent.ps1": "agents/windows/installer/install-agent.ps1",
        "agent/common/identity.py": "agents/common/identity.py",
        "agent/runtime/agent.py": "agents/windows/runtime/agent.py",
        "agent/runtime/capabilities.py": "agents/windows/runtime/capabilities.py",
        "agent/runtime/network_inventory.py": "agents/windows/runtime/network_inventory.py",
        "agent/runtime/update_client.py": "agents/windows/runtime/update_client.py",
        "agent/updater/updater.py": "agents/windows/updater/updater.py",
        "service/register-task.ps1": "agents/windows/service/register-task.ps1",
    }
    files: dict[str, bytes] = {relative: git_file(ref, source) for relative, source in sources.items()}
    files["VERSION"] = (version + "\n").encode()
    files["config/README.md"] = b"Configuration is created during installation. Pairing secrets are never packaged.\n"
    manifest = {
        "schema_version": 1,
        "kind": "CapivaraAgentPackage",
        "platform": "windows",
        "version": version,
        "git_commit": commit,
        "channel": channel,
        "required_files": sorted(files),
        "files": {
            relative: {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
            for relative, data in sorted(files.items())
        },
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    files["manifest.json"] = manifest_bytes

    archive.unlink(missing_ok=True)
    epoch = int(git_text("show", "-s", "--format=%ct", commit))
    # ZIP timestamps cannot predate 1980. Use UTC and a stable lower bound.
    import datetime
    stamp = datetime.datetime.utcfromtimestamp(max(epoch, 315532800))
    date_time = (stamp.year, stamp.month, stamp.day, stamp.hour, stamp.minute, stamp.second)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as package:
        for relative, data in sorted(files.items()):
            info = zipfile.ZipInfo(f"{package_name}/{relative}", date_time=date_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            package.writestr(info, data)

    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    external_manifest.write_bytes(manifest_bytes)
    print(f"Windows Agent package: {archive}")
    print(f"Checksum: {checksum}")
    print(f"Manifest: {external_manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
