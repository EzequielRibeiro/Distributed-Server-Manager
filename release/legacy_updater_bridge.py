#!/usr/bin/env python3
"""Add a package-only bridge for pre-cap-only DSM updaters.

Capivara DSM <= 2.0.46 validates ``bin/dsm`` before handing control to the
updater shipped by the target release. Modern releases are cap-only. This
patcher adds a non-executable archive member solely for that legacy check and
patches the target updater to remove it before final installation validation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import tempfile

BRIDGE_MARKER = "CAPIVARA_RELEASE_UPDATER_BRIDGE_ONLY\n"


def fail(message: str) -> None:
    raise SystemExit(message)


def safe_members(package: tarfile.TarFile) -> tuple[list[tarfile.TarInfo], str, int]:
    members = package.getmembers()
    roots: set[str] = set()
    mtimes: list[int] = []
    for member in members:
        name = member.name.rstrip("/")
        if not name:
            continue
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts:
            fail(f"unsafe archive member: {member.name}")
        roots.add(path.parts[0])
        mtimes.append(int(member.mtime))
        if member.isdev() or member.isfifo():
            fail(f"unsupported archive member: {member.name}")
        if member.issym() or member.islnk():
            target = PurePosixPath(member.linkname)
            if target.is_absolute() or ".." in target.parts:
                fail(f"unsafe archive link: {member.name} -> {member.linkname}")
    if len(roots) != 1:
        fail(f"release archive must have exactly one root, got {sorted(roots)}")
    return members, next(iter(roots)), max(mtimes or [0])


def patch_update(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    old_apply = "    apply_update\n    update_version_file\n"
    new_apply = (
        "    apply_update\n"
        "    # Remove package-only compatibility bridges before the installed tree is valid.\n"
        "    rm -f -- \"${INSTALL_DIR}/bin/dsm\" \"${INSTALL_DIR}/bin/dsm-compat\"\n"
        "    update_version_file\n"
    )
    if old_apply not in text:
        fail("cap-only bridge cleanup anchor not found in update.sh")
    text = text.replace(old_apply, new_apply, 1)

    old_final = (
        "    REQUIRED_FILES=(\n"
        "        \"${INSTALL_DIR}/bin/dsm\"\n"
        "        \"${INSTALL_DIR}/bin/cap\"\n"
        "        \"${INSTALL_DIR}/core/bootstrap.sh\"\n"
        "        \"${INSTALL_DIR}/config/dsm.conf\"\n"
        "    )\n"
    )
    new_final = (
        "    REQUIRED_FILES=(\n"
        "        \"${INSTALL_DIR}/bin/cap\"\n"
        "        \"${INSTALL_DIR}/core/bootstrap.sh\"\n"
        "        \"${INSTALL_DIR}/config/dsm.conf\"\n"
        "    )\n"
    )
    if old_final not in text:
        fail("cap-only final validation anchor not found in update.sh")
    text = text.replace(old_final, new_final, 1)

    old_tail = '    echo\n    echo "Arquivos principais OK."\n    echo "Main files OK."\n}\n'
    new_tail = (
        "    for RETIRED_FILE in \\\n"
        "        \"${INSTALL_DIR}/bin/dsm\" \\\n"
        "        \"${INSTALL_DIR}/bin/dsm-compat\"\n"
        "    do\n"
        "        if [[ -e \"${RETIRED_FILE}\" || -L \"${RETIRED_FILE}\" ]]\n"
        "        then\n"
        "            echo \"Retired CLI artifact remained after update: ${RETIRED_FILE}\" >&2\n"
        "            exit 1\n"
        "        fi\n"
        "    done\n"
        "    echo\n"
        "    echo \"Arquivos principais OK.\"\n"
        "    echo \"Main files OK.\"\n"
        "}\n"
    )
    if old_tail not in text:
        fail("cap-only final validation tail anchor not found in update.sh")
    path.write_text(text.replace(old_tail, new_tail, 1), encoding="utf-8", newline="\n")


def repack(root_parent: Path, root_name: str, archive: Path, mtime: int) -> None:
    tar_cmd = [
        "tar", "--sort=name", f"--mtime=@{mtime}", "--owner=0", "--group=0",
        "--numeric-owner", "-cf", "-", "-C", str(root_parent), root_name,
    ]
    with archive.open("wb") as output:
        tar_process = subprocess.Popen(tar_cmd, stdout=subprocess.PIPE)
        if tar_process.stdout is None:
            fail("unable to capture tar output")
        gzip_process = subprocess.Popen(["gzip", "-n"], stdin=tar_process.stdout, stdout=output)
        tar_process.stdout.close()
        gzip_rc = gzip_process.wait()
        tar_rc = tar_process.wait()
    if tar_rc != 0 or gzip_rc != 0:
        fail(f"repack failed: tar={tar_rc} gzip={gzip_rc}")


def patch_release(archive: Path) -> None:
    archive = archive.resolve()
    if not archive.is_file() or not archive.name.endswith(".tar.gz"):
        fail(f"release archive not found: {archive}")
    with tempfile.TemporaryDirectory(prefix="capivara-legacy-bridge-") as temp:
        temp_path = Path(temp)
        with tarfile.open(archive, "r:gz") as package:
            members, root_name, mtime = safe_members(package)
            package.extractall(temp_path, members=members)
        root = temp_path / root_name
        update = root / "update.sh"
        bridge = root / "bin" / "dsm"
        compat = root / "bin" / "dsm-compat"
        manifest_path = root / "release-manifest.json"
        if not update.is_file() or not manifest_path.is_file():
            fail("release package is missing update.sh or release-manifest.json")
        if bridge.exists() or bridge.is_symlink() or compat.exists() or compat.is_symlink():
            fail("release source unexpectedly contains retired dsm CLI artifacts")

        patch_update(update)
        bridge.write_text(
            BRIDGE_MARKER
            + "This non-executable package member only satisfies the DSM <= 2.0.46 verifier.\n"
            + "The target updater removes it before final installation validation.\n",
            encoding="utf-8",
            newline="\n",
        )
        os.chmod(bridge, 0o644)

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        file_count = sum(1 for item in root.rglob("*") if item.is_file() and not item.is_symlink())
        manifest["file_count"] = file_count
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )

        repack(temp_path, root_name, archive, mtime)
        external_manifest = archive.with_name(archive.name.removesuffix(".tar.gz") + ".manifest.json")
        shutil.copyfile(manifest_path, external_manifest)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        checksum = archive.with_name(archive.name + ".sha256")
        checksum.write_text(f"{digest}  {archive.name}\n", encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    patch_release(args.archive)


if __name__ == "__main__":
    main()
