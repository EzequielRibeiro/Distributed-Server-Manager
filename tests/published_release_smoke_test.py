#!/usr/bin/env python3
"""Validate the assets that GitHub actually published for one Capivara release."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Callable

SEMVER_TAG = re.compile(
    r"^v(?P<version>[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?)$"
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")


class PublishedReleaseError(RuntimeError):
    """A published GitHub release violated the Capivara artifact contract."""


def fail(message: str) -> None:
    raise PublishedReleaseError(message)


def run(*args: str) -> str:
    completed = subprocess.run(
        list(args),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"
        fail(f"{' '.join(args)} failed: {detail}")
    return completed.stdout.strip()


def gh_json(*args: str) -> object:
    output = run("gh", *args)
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        fail(f"GitHub CLI returned invalid JSON for {' '.join(args)}: {exc}")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_safe_member(name: str, root: str) -> None:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        fail(f"archive contains unsafe path: {name}")
    if name != root and not name.startswith(root + "/"):
        fail(f"archive member is outside expected package root {root}: {name}")


def verify_checksum(archive: Path, checksum: Path) -> None:
    lines = [line.strip() for line in checksum.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) != 1:
        fail(f"{checksum.name} must contain exactly one checksum line")
    parts = lines[0].split()
    if len(parts) != 2 or not SHA256.fullmatch(parts[0]) or parts[1].lstrip("*") != archive.name:
        fail(f"{checksum.name} has an invalid sha256sum contract")
    actual = sha256_file(archive)
    if actual != parts[0]:
        fail(f"checksum mismatch for {archive.name}: expected {parts[0]}, got {actual}")


def read_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"unable to read JSON {path.name}: {exc}")
    if not isinstance(payload, dict):
        fail(f"{path.name} must contain a JSON object")
    return payload


def validate_common_manifest(
    manifest: dict,
    *,
    version: str,
    expected_commit: str,
    kind: str,
) -> None:
    if manifest.get("schema_version") != 1:
        fail(f"{kind} manifest has unsupported schema_version")
    if manifest.get("kind") != kind:
        fail(f"expected manifest kind {kind}, got {manifest.get('kind')!r}")
    if manifest.get("version") != version:
        fail(f"{kind} manifest version does not match {version}")
    if manifest.get("git_commit") != expected_commit:
        fail(
            f"{kind} manifest commit {manifest.get('git_commit')!r} "
            f"does not match release tag commit {expected_commit}"
        )


def tar_regular_files(archive: Path, root: str) -> tuple[dict[str, tarfile.TarInfo], Callable[[str], bytes]]:
    package = tarfile.open(archive, "r:gz")
    members = package.getmembers()
    names = [member.name.rstrip("/") for member in members]
    if len(names) != len(set(names)):
        package.close()
        fail(f"{archive.name} contains duplicate archive member names")
    for member in members:
        ensure_safe_member(member.name.rstrip("/"), root)
    files = {
        member.name[len(root) + 1 :]: member
        for member in members
        if member.isfile() and member.name.startswith(root + "/")
    }

    def reader(relative: str) -> bytes:
        member = files.get(relative)
        if member is None:
            fail(f"{archive.name} is missing required regular file {relative}")
        stream = package.extractfile(member)
        if stream is None:
            fail(f"unable to read {relative} from {archive.name}")
        return stream.read()

    setattr(reader, "_package", package)
    return files, reader


def zip_regular_files(archive: Path, root: str) -> tuple[dict[str, zipfile.ZipInfo], Callable[[str], bytes]]:
    package = zipfile.ZipFile(archive, "r")
    infos = package.infolist()
    names = [info.filename.rstrip("/") for info in infos]
    if len(names) != len(set(names)):
        package.close()
        fail(f"{archive.name} contains duplicate archive member names")
    for info in infos:
        ensure_safe_member(info.filename.rstrip("/"), root)
    files = {
        info.filename[len(root) + 1 :]: info
        for info in infos
        if not info.is_dir() and info.filename.startswith(root + "/")
    }

    def reader(relative: str) -> bytes:
        info = files.get(relative)
        if info is None:
            fail(f"{archive.name} is missing required regular file {relative}")
        return package.read(info)

    setattr(reader, "_package", package)
    return files, reader


def close_reader(reader: Callable[[str], bytes]) -> None:
    package = getattr(reader, "_package", None)
    if package is not None:
        package.close()


def validate_dsm(
    directory: Path,
    *,
    version: str,
    expected_commit: str,
) -> None:
    archive = directory / f"capivara-dsm-{version}.tar.gz"
    checksum = directory / f"{archive.name}.sha256"
    external_manifest = directory / f"capivara-dsm-{version}.manifest.json"
    verify_checksum(archive, checksum)
    manifest = read_json(external_manifest)
    validate_common_manifest(
        manifest,
        version=version,
        expected_commit=expected_commit,
        kind="CapivaraReleaseManifest",
    )
    if manifest.get("name") != "capivara-dsm":
        fail("DSM manifest name must be capivara-dsm")
    if manifest.get("archive") != archive.name:
        fail("DSM manifest archive name does not match published archive")

    root = f"capivara-dsm-{version}"
    files, reader = tar_regular_files(archive, root)
    try:
        internal = json.loads(reader("release-manifest.json").decode("utf-8"))
        if internal != manifest:
            fail("published DSM external manifest differs from release-manifest.json inside archive")
        if reader("version").decode("utf-8").strip() != version:
            fail("published DSM archive version file does not match release tag")
        required = manifest.get("required_files")
        if not isinstance(required, list) or not required:
            fail("DSM manifest required_files must be a non-empty list")
        for relative in required:
            if not isinstance(relative, str) or relative not in files:
                fail(f"published DSM archive is missing manifest-required file {relative!r}")
        file_count = manifest.get("file_count")
        if not isinstance(file_count, int) or file_count != len(files):
            fail(
                f"DSM manifest file_count={file_count!r} does not match "
                f"{len(files)} regular files in published archive"
            )
    finally:
        close_reader(reader)


def validate_agent(
    directory: Path,
    *,
    platform: str,
    version: str,
    expected_commit: str,
) -> None:
    if platform == "linux":
        archive = directory / f"capivara-agent-linux-{version}.tar.gz"
        root = f"capivara-agent-linux-{version}"
        open_archive = tar_regular_files
    elif platform == "windows":
        archive = directory / f"capivara-agent-windows-{version}.zip"
        root = f"capivara-agent-windows-{version}"
        open_archive = zip_regular_files
    else:
        fail(f"unsupported platform {platform}")

    checksum = directory / f"{archive.name}.sha256"
    external_manifest = directory / f"{root}.manifest.json"
    verify_checksum(archive, checksum)
    manifest = read_json(external_manifest)
    validate_common_manifest(
        manifest,
        version=version,
        expected_commit=expected_commit,
        kind="CapivaraAgentPackage",
    )
    if manifest.get("platform") != platform:
        fail(f"{platform} Agent manifest reports platform={manifest.get('platform')!r}")
    expected_channel = "beta" if "-" in version else "stable"
    if manifest.get("channel") != expected_channel:
        fail(f"{platform} Agent manifest channel does not match release version")

    required = manifest.get("required_files")
    checks = manifest.get("files")
    if not isinstance(required, list) or not required:
        fail(f"{platform} Agent manifest required_files must be a non-empty list")
    if not isinstance(checks, dict) or set(checks) != set(required):
        fail(f"{platform} Agent manifest files map must exactly cover required_files")

    files, reader = open_archive(archive, root)
    try:
        internal = json.loads(reader("manifest.json").decode("utf-8"))
        if internal != manifest:
            fail(f"published {platform} Agent external manifest differs from archive manifest.json")
        if reader("VERSION").decode("utf-8").strip() != version:
            fail(f"published {platform} Agent VERSION does not match release tag")
        for relative in required:
            if not isinstance(relative, str) or relative not in files:
                fail(f"published {platform} Agent archive is missing required file {relative!r}")
            metadata = checks.get(relative)
            if not isinstance(metadata, dict):
                fail(f"{platform} Agent manifest metadata missing for {relative}")
            data = reader(relative)
            if metadata.get("size") != len(data):
                fail(f"{platform} Agent size mismatch for {relative}")
            digest = metadata.get("sha256")
            if not isinstance(digest, str) or not SHA256.fullmatch(digest):
                fail(f"{platform} Agent manifest has invalid sha256 for {relative}")
            if digest != sha256_bytes(data):
                fail(f"{platform} Agent sha256 mismatch for {relative}")
    finally:
        close_reader(reader)


def release_asset_names(release: object, *, label: str) -> set[str]:
    if not isinstance(release, dict):
        fail(f"{label} release metadata is not an object")
    if release.get("isDraft"):
        fail(f"{label} release is still a draft")
    assets = release.get("assets")
    if not isinstance(assets, list):
        fail(f"{label} release assets metadata is invalid")
    names: set[str] = set()
    for asset in assets:
        if not isinstance(asset, dict):
            fail(f"{label} release contains invalid asset metadata")
        name = asset.get("name")
        size = asset.get("size")
        if not isinstance(name, str) or not name:
            fail(f"{label} release contains an unnamed asset")
        if name in names:
            fail(f"{label} release contains duplicate asset name {name}")
        if not isinstance(size, int) or size <= 0:
            fail(f"{label} release asset {name} is empty")
        names.add(name)
    return names


def resolve_commit(repo: str, tag: str) -> str:
    commit = run("gh", "api", f"repos/{repo}/commits/{tag}", "--jq", ".sha")
    if not COMMIT.fullmatch(commit):
        fail(f"unable to resolve {tag} to a 40-character commit SHA")
    return commit


def download_release_assets(repo: str, tag: str, directory: Path, required: set[str]) -> None:
    command = ["gh", "release", "download", tag, "--repo", repo, "--dir", str(directory)]
    for name in sorted(required):
        command.extend(["--pattern", name])
    run(*command)
    missing = sorted(name for name in required if not (directory / name).is_file())
    if missing:
        fail(f"GitHub release download did not produce required assets: {', '.join(missing)}")


def validate_standalone_release(
    repo: str,
    *,
    platform: str,
    version: str,
    canonical_dir: Path,
) -> None:
    tag = f"agent-{platform}-v{version}"
    release = gh_json(
        "release",
        "view",
        tag,
        "--repo",
        repo,
        "--json",
        "tagName,isDraft,isPrerelease,assets",
    )
    if not isinstance(release, dict) or release.get("tagName") != tag:
        fail(f"standalone {platform} release tag metadata does not match {tag}")
    expected_commit = resolve_commit(repo, tag)
    canonical_tag = f"v{version}"
    canonical_commit = resolve_commit(repo, canonical_tag)
    if expected_commit != canonical_commit:
        fail(
            f"standalone {platform} tag {tag} points to {expected_commit}, "
            f"not canonical release commit {canonical_commit}"
        )

    if platform == "linux":
        archive = f"capivara-agent-linux-{version}.tar.gz"
    else:
        archive = f"capivara-agent-windows-{version}.zip"
    required = {archive, f"{archive}.sha256", f"capivara-agent-{platform}-{version}.manifest.json"}
    names = release_asset_names(release, label=f"standalone {platform}")
    missing = sorted(required - names)
    if missing:
        fail(f"standalone {platform} release is missing assets: {', '.join(missing)}")

    with tempfile.TemporaryDirectory(prefix=f"capivara-{platform}-release-") as temp:
        directory = Path(temp)
        download_release_assets(repo, tag, directory, required)
        for name in required:
            canonical = canonical_dir / name
            standalone = directory / name
            if not canonical.is_file():
                fail(f"canonical release is missing {name} for standalone comparison")
            if sha256_file(canonical) != sha256_file(standalone):
                fail(f"standalone {platform} asset {name} differs from canonical release")


def validate_release(repo: str, tag: str, *, validate_standalone: bool = True) -> None:
    match = SEMVER_TAG.fullmatch(tag)
    if not match:
        fail(f"canonical release tag must be v<SemVer>, got {tag!r}")
    version = match.group("version")
    release = gh_json(
        "release",
        "view",
        tag,
        "--repo",
        repo,
        "--json",
        "tagName,isDraft,isPrerelease,assets",
    )
    if not isinstance(release, dict) or release.get("tagName") != tag:
        fail(f"GitHub release metadata tag does not match requested tag {tag}")

    expected_commit = resolve_commit(repo, tag)
    stable = "-" not in version
    if bool(release.get("isPrerelease")) == stable:
        fail(
            f"release prerelease flag does not match version {version}: "
            f"isPrerelease={release.get('isPrerelease')!r}"
        )

    dsm_archive = f"capivara-dsm-{version}.tar.gz"
    linux_archive = f"capivara-agent-linux-{version}.tar.gz"
    windows_archive = f"capivara-agent-windows-{version}.zip"
    required = {
        dsm_archive,
        f"{dsm_archive}.sha256",
        f"capivara-dsm-{version}.manifest.json",
        linux_archive,
        f"{linux_archive}.sha256",
        f"capivara-agent-linux-{version}.manifest.json",
        windows_archive,
        f"{windows_archive}.sha256",
        f"capivara-agent-windows-{version}.manifest.json",
    }
    names = release_asset_names(release, label="canonical")
    missing = sorted(required - names)
    if missing:
        fail(f"canonical release is missing required assets: {', '.join(missing)}")

    with tempfile.TemporaryDirectory(prefix="capivara-published-release-") as temp:
        directory = Path(temp)
        download_release_assets(repo, tag, directory, required)
        validate_dsm(directory, version=version, expected_commit=expected_commit)
        validate_agent(
            directory,
            platform="linux",
            version=version,
            expected_commit=expected_commit,
        )
        validate_agent(
            directory,
            platform="windows",
            version=version,
            expected_commit=expected_commit,
        )
        if validate_standalone:
            validate_standalone_release(
                repo,
                platform="linux",
                version=version,
                canonical_dir=directory,
            )
            validate_standalone_release(
                repo,
                platform="windows",
                version=version,
                canonical_dir=directory,
            )

    print(
        f"Published release smoke passed: {repo} {tag} "
        f"({expected_commit}) canonical + Linux/Windows standalone assets"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="GitHub repository in owner/name form")
    parser.add_argument("--tag", required=True, help="Canonical release tag, for example v2.0.42")
    parser.add_argument(
        "--canonical-only",
        action="store_true",
        help="Skip the standalone Linux/Windows release identity comparison",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        validate_release(args.repo, args.tag, validate_standalone=not args.canonical_only)
    except PublishedReleaseError as exc:
        print(f"Published release smoke failed: {exc}", file=__import__("sys").stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
