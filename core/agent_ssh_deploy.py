#!/usr/bin/env python3
"""Remote Agent bootstrap over OpenSSH.

SSH is used only for first-install bootstrap. Linux and Windows share the
transport, while keeping platform-specific preflight and bootstrap commands.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import tarfile
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Sequence


class AgentDeployError(RuntimeError):
    pass


@dataclass(frozen=True)
class SSHDeployOptions:
    host: str
    ssh_user: str
    ssh_port: int = 22
    identity_file: str | None = None
    connect_timeout: int = 10
    password_file: str | None = None


@dataclass(frozen=True)
class SSHResult:
    returncode: int
    stdout: str
    stderr: str


SSHRunner = Callable[[Sequence[str], str | None, int | None], SSHResult]
_HOST_RE = re.compile(r"^[A-Za-z0-9._:-]{1,253}$")
_USER_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def validate_host(value: str) -> str:
    host = str(value or "").strip()
    if not host or not _HOST_RE.fullmatch(host):
        raise AgentDeployError("invalid SSH host")
    candidate = host[1:-1] if host.startswith("[") and host.endswith("]") else host
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        labels = candidate.rstrip(".").split(".")
        if any(
            not label
            or len(label) > 63
            or label.startswith("-")
            or label.endswith("-")
            for label in labels
        ):
            raise AgentDeployError("invalid SSH host")
    return candidate


def validate_ssh_user(value: str) -> str:
    user = str(value or "").strip()
    if not _USER_RE.fullmatch(user):
        raise AgentDeployError("invalid SSH user")
    return user


def validate_password_file(value: str) -> Path:
    path = Path(os.path.expanduser(str(value or ""))).resolve()
    if not path.is_file():
        raise AgentDeployError(f"SSH password file not found: {path}")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise AgentDeployError(
            f"SSH password file has unsafe permissions {mode:04o}; "
            "use 0600 or more restrictive"
        )
    try:
        secret = path.read_text(encoding="utf-8").rstrip("\r\n")
    except PermissionError as exc:
        raise AgentDeployError(
            f"SSH password file is not readable by the Capivara service: {path}; "
            "recreate it with 'sudo cap agent secret create NAME'"
        ) from exc
    except UnicodeDecodeError as exc:
        raise AgentDeployError("SSH password file must be UTF-8 text") from exc
    if not secret:
        raise AgentDeployError("SSH password file is empty")
    return path


def _password_text(options: SSHDeployOptions) -> str | None:
    if not options.password_file:
        return None
    return validate_password_file(options.password_file).read_text(
        encoding="utf-8"
    ).rstrip("\r\n")


def _default_runner(
    argv: Sequence[str], stdin_text: str | None, timeout: int | None
) -> SSHResult:
    process = subprocess.run(
        list(argv),
        input=stdin_text,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    return SSHResult(process.returncode, process.stdout, process.stderr)


def build_ssh_argv(options: SSHDeployOptions, remote_command: str) -> list[str]:
    host = validate_host(options.host)
    user = validate_ssh_user(options.ssh_user)
    if not 1 <= int(options.ssh_port) <= 65535:
        raise AgentDeployError("ssh_port must be between 1 and 65535")
    if not 1 <= int(options.connect_timeout) <= 300:
        raise AgentDeployError("connect_timeout must be between 1 and 300 seconds")
    if options.identity_file and options.password_file:
        raise AgentDeployError("use either identity_file or password_file, not both")

    password_path = (
        validate_password_file(options.password_file) if options.password_file else None
    )
    argv: list[str] = []
    if password_path:
        argv.extend(["sshpass", "-f", str(password_path)])
    argv.extend(
        [
            "ssh",
            "-p",
            str(int(options.ssh_port)),
            "-o",
            f"ConnectTimeout={int(options.connect_timeout)}",
            "-o",
            "BatchMode=no" if password_path else "BatchMode=yes",
            # Trust-on-first-use: a new host key is persisted in known_hosts,
            # while a changed key remains a hard failure.
            "-o",
            "StrictHostKeyChecking=accept-new",
        ]
    )
    if password_path:
        argv.extend(
            ["-o", "PreferredAuthentications=password,keyboard-interactive"]
        )
    if options.identity_file:
        identity = Path(os.path.expanduser(str(options.identity_file))).resolve()
        if not identity.is_file():
            raise AgentDeployError(f"SSH identity file not found: {identity}")
        argv.extend(["-i", str(identity)])
    argv.extend([f"{user}@{host}", remote_command])
    return argv



def build_scp_argv(
    options: SSHDeployOptions,
    local_path: str | Path,
    remote_path: str,
) -> list[str]:
    host = validate_host(options.host)
    user = validate_ssh_user(options.ssh_user)

    if not 1 <= int(options.ssh_port) <= 65535:
        raise AgentDeployError("ssh_port must be between 1 and 65535")
    if not 1 <= int(options.connect_timeout) <= 300:
        raise AgentDeployError(
            "connect_timeout must be between 1 and 300 seconds"
        )
    if options.identity_file and options.password_file:
        raise AgentDeployError(
            "use either identity_file or password_file, not both"
        )

    source = Path(local_path).expanduser().resolve()
    if not source.is_file():
        raise AgentDeployError(
            f"local Agent package not found: {source}"
        )

    if not re.fullmatch(
        r"/tmp/capivara-agent-package-[0-9a-f]{32}\.tar\.gz",
        remote_path,
    ):
        raise AgentDeployError("unsafe remote Agent package path")

    password_path = (
        validate_password_file(options.password_file)
        if options.password_file
        else None
    )

    argv: list[str] = []

    if password_path:
        argv.extend(["sshpass", "-f", str(password_path)])

    argv.extend([
        "scp",
        "-P",
        str(int(options.ssh_port)),
        "-o",
        f"ConnectTimeout={int(options.connect_timeout)}",
        "-o",
        "BatchMode=no" if password_path else "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ])

    if password_path:
        argv.extend([
            "-o",
            "PreferredAuthentications=password,keyboard-interactive",
        ])

    if options.identity_file:
        identity = Path(
            os.path.expanduser(str(options.identity_file))
        ).resolve()

        if not identity.is_file():
            raise AgentDeployError(
                f"SSH identity file not found: {identity}"
            )

        argv.extend(["-i", str(identity)])

    scp_host = f"[{host}]" if ":" in host else host

    argv.extend([
        str(source),
        f"{user}@{scp_host}:{remote_path}",
    ])

    return argv


def _run_scp(
    options: SSHDeployOptions,
    local_path: str | Path,
    remote_path: str,
    *,
    runner: SSHRunner = _default_runner,
    timeout: int | None = None,
) -> SSHResult:
    if runner is _default_runner:
        if shutil.which("scp") is None:
            raise AgentDeployError("OpenSSH scp client not found")

        if options.password_file and shutil.which("sshpass") is None:
            raise AgentDeployError(
                "password-file authentication requires sshpass "
                "on the Controller; SSH keys remain preferred"
            )

    try:
        return runner(
            build_scp_argv(options, local_path, remote_path),
            None,
            timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise AgentDeployError(
            "Agent package transfer timed out"
        ) from exc
    except OSError as exc:
        raise AgentDeployError(
            f"unable to execute scp client: {exc}"
        ) from exc


def validate_agent_package_file(value: str | Path) -> Path:
    path = Path(value).expanduser().resolve()

    if not path.is_file():
        raise AgentDeployError(
            f"local Agent package not found: {path}"
        )

    try:
        archive = tarfile.open(path, "r:gz")
    except (tarfile.TarError, OSError) as exc:
        raise AgentDeployError(
            f"invalid Linux Agent package: {path}"
        ) from exc

    try:
        members: dict[str, tarfile.TarInfo] = {}
        roots: set[str] = set()

        for member in archive.getmembers():
            raw = member.name

            while raw.startswith("./"):
                raw = raw[2:]

            if not raw:
                continue

            parts = PurePosixPath(raw).parts

            if (
                raw.startswith("/")
                or ".." in parts
                or member.issym()
                or member.islnk()
            ):
                raise AgentDeployError(
                    f"unsafe path in Agent package: {member.name}"
                )

            if not parts:
                continue

            roots.add(parts[0])
            members[raw.rstrip("/")] = member

        if len(roots) != 1:
            raise AgentDeployError(
                "Agent package must contain exactly one top-level directory"
            )

        package_root = next(iter(roots))

        def package_member(relative: str) -> tarfile.TarInfo | None:
            return members.get(
                f"{package_root}/{relative}"
            )

        for required in (
            "install-agent.sh",
            "manifest.json",
            "VERSION",
        ):
            member = package_member(required)

            if member is None or not member.isfile():
                raise AgentDeployError(
                    f"invalid Agent package: missing {required}"
                )

        manifest_member = package_member(
            "manifest.json"
        )
        version_member = package_member(
            "VERSION"
        )

        assert manifest_member is not None
        assert version_member is not None

        manifest_fp = archive.extractfile(
            manifest_member
        )
        version_fp = archive.extractfile(
            version_member
        )

        if manifest_fp is None or version_fp is None:
            raise AgentDeployError(
                "invalid Agent package metadata"
            )

        manifest = json.loads(
            manifest_fp.read().decode("utf-8")
        )

        version = (
            version_fp.read()
            .decode("utf-8")
            .strip()
        )

        if manifest.get("kind") != "CapivaraAgentPackage":
            raise AgentDeployError(
                "invalid Agent package kind"
            )

        if manifest.get("schema_version") != 1:
            raise AgentDeployError(
                "unsupported Agent package manifest schema"
            )

        if manifest.get("platform") != "linux":
            raise AgentDeployError(
                "local package is not a Linux Agent package"
            )

        if str(manifest.get("version") or "") != version:
            raise AgentDeployError(
                "Agent package version differs from manifest"
            )

        required_files = manifest.get(
            "required_files"
        )

        files = manifest.get("files")

        if (
            not isinstance(required_files, list)
            or not isinstance(files, dict)
        ):
            raise AgentDeployError(
                "invalid Agent package manifest structure"
            )

        for rel_value in required_files:
            rel = str(rel_value)

            rel_parts = PurePosixPath(rel).parts

            if (
                not rel
                or rel.startswith("/")
                or ".." in rel_parts
            ):
                raise AgentDeployError(
                    f"unsafe Agent manifest path: {rel}"
                )

            member = package_member(rel)

            metadata = files.get(rel)

            if (
                member is None
                or not member.isfile()
                or not isinstance(metadata, dict)
            ):
                raise AgentDeployError(
                    f"invalid Agent package manifest entry: {rel}"
                )

            expected = str(
                metadata.get("sha256") or ""
            )

            if not re.fullmatch(
                r"[0-9a-f]{64}",
                expected,
            ):
                raise AgentDeployError(
                    f"invalid Agent package SHA-256 entry: {rel}"
                )

            source = archive.extractfile(
                member
            )

            if source is None:
                raise AgentDeployError(
                    f"unable to read Agent package file: {rel}"
                )

            data = source.read()

            actual = hashlib.sha256(
                data
            ).hexdigest()

            if actual != expected:
                raise AgentDeployError(
                    f"Agent package SHA-256 mismatch: {rel}"
                )

            expected_size = metadata.get("size")

            if (
                expected_size is not None
                and int(expected_size) != len(data)
            ):
                raise AgentDeployError(
                    f"Agent package size mismatch: {rel}"
                )

    except (
        json.JSONDecodeError,
        UnicodeDecodeError,
        TypeError,
        ValueError,
    ) as exc:
        raise AgentDeployError(
            "invalid Agent package metadata"
        ) from exc
    finally:
        archive.close()

    return path



def _local_package_bootstrap_stdin(
    controller_url: str,
    pairing_token: str,
    remote_package_path: str,
) -> str:
    payload = json.dumps(
        {
            "controller_url": controller_url,
            "pairing_token": pairing_token,
            "package_path": remote_package_path,
        },
        separators=(",", ":"),
    )

    return f'''import json, os, pathlib, shutil, subprocess, sys, tarfile, tempfile
payload=json.loads({payload!r})
archive_path=pathlib.Path(payload["package_path"])
work=pathlib.Path(tempfile.mkdtemp(prefix="capivara-agent-local-"))
try:
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            root=work.resolve()
            for member in archive.getmembers():
                raw=member.name
                while raw.startswith("./"):
                    raw=raw[2:]
                parts=pathlib.PurePosixPath(raw).parts
                if (
                    not raw
                    or raw.startswith("/")
                    or ".." in parts
                    or member.issym()
                    or member.islnk()
                ):
                    print(
                        "CAPIVARA_BOOTSTRAP_ERROR: "
                        "unsafe Agent package path: %s" % member.name,
                        file=sys.stderr,
                    )
                    raise SystemExit(1)

                target=(work/pathlib.Path(*parts)).resolve()

                if target != root and root not in target.parents:
                    print(
                        "CAPIVARA_BOOTSTRAP_ERROR: "
                        "Agent package path escaped extraction root",
                        file=sys.stderr,
                    )
                    raise SystemExit(1)

            archive.extractall(work)

    except (tarfile.TarError, OSError) as exc:
        print(
            "CAPIVARA_BOOTSTRAP_ERROR: "
            "unable to extract local Agent package: %s" % exc,
            file=sys.stderr,
        )
        raise SystemExit(1)

    roots=[
        item
        for item in work.iterdir()
        if item.is_dir()
    ]

    if len(roots) != 1:
        print(
            "CAPIVARA_BOOTSTRAP_ERROR: "
            "Agent package must contain exactly one top-level directory",
            file=sys.stderr,
        )
        raise SystemExit(1)

    package_root=roots[0]
    installer=package_root/"install-agent.sh"

    if not installer.is_file():
        print(
            "CAPIVARA_BOOTSTRAP_ERROR: "
            "install-agent.sh missing from local Agent package",
            file=sys.stderr,
        )
        raise SystemExit(1)

    env=os.environ.copy()
    env["CAPIVARA_PAIRING_TOKEN"]=payload["pairing_token"]

    install=subprocess.run(
        [
            "bash",
            str(installer),
            "--controller-url",
            payload["controller_url"],
            "--package-dir",
            str(package_root),
        ],
        check=False,
        env=env,
    )

    if install.returncode:
        print(
            "CAPIVARA_BOOTSTRAP_ERROR: "
            "Agent installer exited with status %d"
            % install.returncode,
            file=sys.stderr,
        )
        raise SystemExit(install.returncode)
finally:
    shutil.rmtree(work, ignore_errors=True)
    try:
        archive_path.unlink()
    except FileNotFoundError:
        pass
'''


def bootstrap_agent_package(
    options: SSHDeployOptions,
    *,
    controller_url: str,
    pairing_token: str,
    package_file: str | Path,
    runner: SSHRunner = _default_runner,
    transfer_runner: SSHRunner = _default_runner,
    timeout: int = 900,
) -> None:
    controller_url = str(
        controller_url or ""
    ).strip().rstrip("/")

    pairing_token = str(
        pairing_token or ""
    ).strip()

    if not controller_url.startswith(
        ("http://", "https://")
    ):
        raise AgentDeployError(
            "controller_url must use http:// or https://"
        )

    if not pairing_token:
        raise AgentDeployError(
            "pairing token is required"
        )

    package = validate_agent_package_file(
        package_file
    )

    remote_path = (
        "/tmp/capivara-agent-package-"
        + secrets.token_hex(16)
        + ".tar.gz"
    )

    transfer = _run_scp(
        options,
        package,
        remote_path,
        runner=transfer_runner,
        timeout=timeout,
    )

    if transfer.returncode != 0:
        raise AgentDeployError(
            "Agent package transfer failed: "
            + _reason(
                transfer,
                "remote Agent package transfer failed",
            )
        )

    user = validate_ssh_user(options.ssh_user)
    password = _password_text(options)

    script = _local_package_bootstrap_stdin(
        controller_url,
        pairing_token,
        remote_path,
    )

    if user == "root":
        command = "python3 -"
        stdin_text = script
    elif password is not None:
        command = "sudo -S -p '' python3 -"
        stdin_text = password + "\n" + script
    else:
        command = "sudo -n python3 -"
        stdin_text = script

    result = _run_ssh(
        options,
        command,
        runner=runner,
        stdin_text=stdin_text,
        timeout=timeout,
    )

    if result.returncode != 0:
        try:
            _run_ssh(
                options,
                f"rm -f -- {remote_path}",
                runner=runner,
                timeout=options.connect_timeout + 5,
            )
        except AgentDeployError:
            pass

        raise AgentDeployError(
            "Agent local package bootstrap failed: "
            + _reason(
                result,
                "remote Agent local package bootstrap failed",
            )
        )


def _run_ssh(
    options: SSHDeployOptions,
    remote_command: str,
    *,
    runner: SSHRunner,
    stdin_text: str | None = None,
    timeout: int | None = None,
) -> SSHResult:
    if runner is _default_runner:
        if shutil.which("ssh") is None:
            raise AgentDeployError("OpenSSH client not found")
        if options.password_file and shutil.which("sshpass") is None:
            raise AgentDeployError(
                "password-file authentication requires sshpass on the Controller; "
                "SSH keys remain preferred"
            )
    try:
        return runner(build_ssh_argv(options, remote_command), stdin_text, timeout)
    except subprocess.TimeoutExpired as exc:
        raise AgentDeployError("SSH operation timed out") from exc
    except OSError as exc:
        raise AgentDeployError(f"unable to execute SSH client: {exc}") from exc


def _reason(result: SSHResult, fallback: str) -> str:
    stderr = str(result.stderr or "").strip()
    stdout = str(result.stdout or "").strip()
    combined = "\n".join(part for part in (stderr, stdout) if part).strip()
    lowered = combined.lower()

    # sshpass uses 5 for an invalid/rejected password. This often arrives with
    # an empty stderr, so classify it before falling back to a generic message.
    if result.returncode == 5:
        return "SSH authentication failed; verify the password file or use an SSH key"
    if "permission denied" in lowered and "sudo" not in lowered:
        return "SSH authentication failed; verify the selected user and credential"
    if "host key verification failed" in lowered or "remote host identification has changed" in lowered:
        return "SSH host key verification failed; inspect the stored host fingerprint"
    if "sudo:" in lowered and (
        "incorrect password" in lowered
        or "a password is required" in lowered
        or "not in the sudoers" in lowered
        or "is not allowed to execute" in lowered
    ):
        return "remote sudo authentication/authorization failed for the SSH user"
    if "could not resolve hostname" in lowered:
        return "SSH host name could not be resolved"
    if "connection refused" in lowered:
        return "SSH connection refused by the remote host"
    if "connection timed out" in lowered or "operation timed out" in lowered:
        return "SSH connection timed out"

    # Remote bootstrap scripts emit explicit markers on stderr. Prefer those
    # over stdout progress lines such as "Pacote validado por SHA-256" so a
    # successful progress message can never mask the actual install failure.
    stderr_lines = [line.strip() for line in stderr.splitlines() if line.strip()]

    # A mensagem específica do instalador tem precedência sobre o marcador
    # genérico produzido pelo bootstrap pai.
    specific = [
        line for line in stderr_lines
        if "[Capivara Agent][ERRO]" in line
    ]
    if specific:
        return specific[-1]

    bootstrap_markers = [
        line for line in stderr_lines
        if "CAPIVARA_BOOTSTRAP_ERROR:" in line
    ]
    if bootstrap_markers:
        # Com `set -e`, alguns comandos (apt, python, install, systemctl etc.)
        # podem abortar sem passar por fail(). Nesse caso preserve a última
        # linha real de stderr anterior ao marcador genérico.
        non_markers = [
            line for line in stderr_lines
            if "CAPIVARA_BOOTSTRAP_ERROR:" not in line
        ]
        if non_markers:
            return f"{non_markers[-1]} | {bootstrap_markers[-1]}"
        return bootstrap_markers[-1]

    if stderr_lines:
        return stderr_lines[-1]

    stdout_lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    errorish = [
        line
        for line in stdout_lines
        if any(token in line.lower() for token in ("error", "erro", "failed", "falhou", "traceback"))
    ]
    if errorish:
        return errorish[-1]
    return stdout_lines[-1] if stdout_lines else fallback


def preflight_ssh(
    options: SSHDeployOptions, *, runner: SSHRunner = _default_runner
) -> dict[str, Any]:
    user = validate_ssh_user(options.ssh_user)
    password = _password_text(options)
    base = (
        'set -eu; test "$(uname -s)" = Linux; '
        "command -v bash >/dev/null; command -v curl >/dev/null; "
        "command -v python3 >/dev/null; "
    )
    stdin_text = None
    if user != "root":
        base += "command -v sudo >/dev/null; "
        if password is not None:
            base += "sudo -S -p '' true; "
            stdin_text = password + "\n"
        else:
            base += "sudo -n true; "
    base += (
        "if command -v dpkg >/dev/null 2>&1; then "
        "audit=$(dpkg --audit 2>&1 || true); "
        "if [ -n \"$audit\" ]; then "
        "printf '%s\\n' \"$audit\" >&2; "
        "printf 'CAPIVARA_PACKAGE_MANAGER_NOT_READY: dpkg audit reported incomplete package state\\n' >&2; "
        "exit 42; "
        "fi; "
        "if [ -d /var/lib/dpkg/updates ] && "
        "find /var/lib/dpkg/updates -mindepth 1 -maxdepth 1 -type f -print -quit 2>/dev/null | grep -q .; then "
        "printf 'CAPIVARA_PACKAGE_MANAGER_NOT_READY: dpkg has pending update state; run dpkg --configure -a\\n' >&2; "
        "exit 42; "
        "fi; "
        "fi; "
    )
    base += (
        "if command -v dpkg >/dev/null 2>&1; then "
        "audit=$(dpkg --audit 2>&1 || true); "
        "if [ -n \"$audit\" ]; then "
        "printf '%s\\n' \"$audit\" >&2; "
        "printf 'CAPIVARA_PACKAGE_MANAGER_NOT_READY: dpkg audit reported incomplete package state\\n' >&2; "
        "exit 42; "
        "fi; "
        "if [ -d /var/lib/dpkg/updates ] && "
        "find /var/lib/dpkg/updates -mindepth 1 -maxdepth 1 -type f -print -quit 2>/dev/null | grep -q .; then "
        "printf 'CAPIVARA_PACKAGE_MANAGER_NOT_READY: dpkg has pending update state; run dpkg --configure -a\\n' >&2; "
        "exit 42; "
        "fi; "
        "fi; "
    )
    command = base + 'printf "CAPIVARA_PREFLIGHT_OK\\n"; uname -m'
    result = _run_ssh(
        options,
        command,
        runner=runner,
        stdin_text=stdin_text,
        timeout=options.connect_timeout + 10,
    )
    if result.returncode != 0 or "CAPIVARA_PREFLIGHT_OK" not in result.stdout:
        requirement = (
            "root or sudo access" if password is not None else "root/passwordless sudo"
        )
        reason = _reason(result, "remote preflight failed")
        if "CAPIVARA_PACKAGE_MANAGER_NOT_READY:" in result.stderr:
            raise AgentDeployError(
                "SSH preflight failed: remote Linux package manager is not ready: "
                + reason
            )
        raise AgentDeployError(
            f"SSH preflight failed (Linux, curl, bash, python3 and {requirement} "
            f"are required): {reason}"
        )
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return {
        "platform": "linux",
        "architecture": lines[-1] if lines else "unknown",
        "transport": "openssh",
        "privilege": (
            "root"
            if user == "root"
            else "sudo-password"
            if password is not None
            else "sudo-noninteractive"
        ),
    }


def preflight_windows_ssh(
    options: SSHDeployOptions, *, runner: SSHRunner = _default_runner
) -> dict[str, Any]:
    powershell = (
        "$ErrorActionPreference='Stop';"
        "$id=[Security.Principal.WindowsIdentity]::GetCurrent();"
        "$p=New-Object Security.Principal.WindowsPrincipal($id);"
        "if(-not $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){exit 41};"
        "Write-Output 'CAPIVARA_WINDOWS_PREFLIGHT_OK';"
        "Write-Output $env:PROCESSOR_ARCHITECTURE"
    )
    result = _run_ssh(
        options,
        'powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "'
        + powershell
        + '"',
        runner=runner,
        timeout=options.connect_timeout + 15,
    )
    if (
        result.returncode != 0
        or "CAPIVARA_WINDOWS_PREFLIGHT_OK" not in result.stdout
    ):
        raise AgentDeployError(
            "SSH preflight failed (Windows OpenSSH, PowerShell and an Administrator "
            "account are required): "
            + _reason(result, "remote Windows preflight failed")
        )
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return {
        "platform": "windows",
        "architecture": lines[-1] if lines else "unknown",
        "transport": "openssh",
    }


def remote_agent_present(
    options: SSHDeployOptions, *, runner: SSHRunner = _default_runner
) -> bool:
    """Fail closed when any strong Linux Agent installation marker exists."""
    command = (
        "test "
        "-f /etc/capivara-agent/agent.json "
        "-o -f /var/lib/capivara-agent/identity.json "
        "-o -f /etc/capivara-agent/agent.conf "
        "-o -f /etc/systemd/system/capivara-agent.service "
        "-o -f /opt/capivara-agent/runtime/agent.py"
    )
    return (
        _run_ssh(
            options,
            command,
            runner=runner,
            timeout=options.connect_timeout + 5,
        ).returncode
        == 0
    )


def remote_windows_agent_present_ssh(
    options: SSHDeployOptions, *, runner: SSHRunner = _default_runner
) -> bool:
    powershell = (
        "$p=@('C:\\ProgramData\\Capivara\\Agent\\identity.json',"
        "'C:\\ProgramData\\Capivara\\Agent\\agent.conf');"
        "if($p|Where-Object{Test-Path $_}){exit 0}else{exit 1}"
    )
    return (
        _run_ssh(
            options,
            'powershell.exe -NoProfile -NonInteractive -Command "'
            + powershell
            + '"',
            runner=runner,
            timeout=options.connect_timeout + 5,
        ).returncode
        == 0
    )


def _bootstrap_stdin(
    controller_url: str, pairing_token: str, release_tag: str = "latest"
) -> str:
    payload = json.dumps(
        {
            "controller_url": controller_url,
            "pairing_token": pairing_token,
            "release_tag": release_tag,
        },
        separators=(",", ":"),
    )
    return f'''import json, os, subprocess, tempfile\npayload=json.loads({payload!r})\nurl=payload["controller_url"].rstrip("/")+"/agent/install.sh"\nfd,path=tempfile.mkstemp(prefix="capivara-agent-bootstrap-",suffix=".sh"); os.close(fd)\ntry:\n download=subprocess.run(["curl","-fsSL",url,"-o",path],check=False)\n if download.returncode:\n  print("CAPIVARA_BOOTSTRAP_ERROR: failed to download /agent/install.sh (curl exit %d)" % download.returncode, file=__import__("sys").stderr)\n  raise SystemExit(download.returncode)\n os.chmod(path,0o700)\n env=os.environ.copy(); env["CAPIVARA_PAIRING_TOKEN"]=payload["pairing_token"]; env["CAPIVARA_RELEASE_TAG"]=payload["release_tag"]\n install=subprocess.run(["bash",path,"--controller-url",payload["controller_url"]],check=False,env=env)\n if install.returncode:\n  print("CAPIVARA_BOOTSTRAP_ERROR: Agent installer exited with status %d" % install.returncode, file=__import__("sys").stderr)\n  raise SystemExit(install.returncode)\nfinally:\n try: os.unlink(path)\n except FileNotFoundError: pass\n'''


def bootstrap_agent(
    options: SSHDeployOptions,
    *,
    controller_url: str,
    pairing_token: str,
    release_tag: str = "latest",
    runner: SSHRunner = _default_runner,
    timeout: int = 900,
) -> None:
    controller_url = str(controller_url or "").strip().rstrip("/")
    pairing_token = str(pairing_token or "").strip()
    release_tag = str(release_tag or "latest").strip()
    if not controller_url.startswith(("http://", "https://")):
        raise AgentDeployError("controller_url must use http:// or https://")
    if not pairing_token:
        raise AgentDeployError("pairing token is required")
    user = validate_ssh_user(options.ssh_user)
    password = _password_text(options)
    script = _bootstrap_stdin(controller_url, pairing_token, release_tag)
    if user == "root":
        command = "python3 -"
        stdin_text = script
    elif password is not None:
        command = "sudo -S -p '' python3 -"
        stdin_text = password + "\n" + script
    else:
        command = "sudo -n python3 -"
        stdin_text = script
    result = _run_ssh(
        options,
        command,
        runner=runner,
        stdin_text=stdin_text,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise AgentDeployError(
            "Agent bootstrap failed: "
            + _reason(result, "remote Agent bootstrap failed")
        )


def _windows_bootstrap_stdin(
    controller_url: str, pairing_token: str, release_tag: str
) -> str:
    payload = json.dumps(
        {
            "controller_url": controller_url,
            "pairing_token": pairing_token,
            "release_tag": release_tag,
        }
    ).replace("'", "''")
    return (
        "$ErrorActionPreference='Stop'\n"
        f"$payload=ConvertFrom-Json '{payload}'\n"
        "$url=$payload.controller_url.TrimEnd('/')+'/agent/install.ps1'\n"
        "$script=(Invoke-WebRequest -UseBasicParsing -Uri $url).Content\n"
        "& ([scriptblock]::Create($script)) -ControllerUrl $payload.controller_url "
        "-PairingToken $payload.pairing_token -ReleaseTag $payload.release_tag\n"
    )


def bootstrap_windows_agent_ssh(
    options: SSHDeployOptions,
    *,
    controller_url: str,
    pairing_token: str,
    release_tag: str = "latest",
    runner: SSHRunner = _default_runner,
    timeout: int = 900,
) -> None:
    controller_url = str(controller_url or "").strip().rstrip("/")
    pairing_token = str(pairing_token or "").strip()
    release_tag = str(release_tag or "latest").strip()
    if not controller_url.startswith(("http://", "https://")):
        raise AgentDeployError("controller_url must use http:// or https://")
    if not pairing_token:
        raise AgentDeployError("pairing token is required")
    result = _run_ssh(
        options,
        "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command -",
        runner=runner,
        stdin_text=_windows_bootstrap_stdin(
            controller_url, pairing_token, release_tag
        ),
        timeout=timeout,
    )
    if result.returncode != 0:
        raise AgentDeployError(
            "Windows Agent bootstrap failed: "
            + _reason(result, "remote Windows Agent bootstrap failed")
        )


def wait_for_agent_online(
    status_reader: Callable[[], dict[str, Any]],
    *,
    timeout: int = 180,
    interval: float = 2.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + max(1, int(timeout))
    latest: dict[str, Any] = {}
    while time.monotonic() < deadline:
        latest = dict(status_reader() or {})
        if (
            str(latest.get("agent_status", "")).lower() == "active"
            and str(latest.get("health_status", "")).lower() == "online"
        ):
            return latest
        time.sleep(max(0.05, float(interval)))
    raise AgentDeployError(
        "Agent enrollment did not reach active/online before timeout"
        + (f" (last state: {latest})" if latest else "")
    )


__all__ = [
    "AgentDeployError",
    "SSHDeployOptions",
    "SSHResult",
    "bootstrap_agent",
    "bootstrap_windows_agent_ssh",
    "build_ssh_argv",
    "preflight_ssh",
    "preflight_windows_ssh",
    "remote_agent_present",
    "remote_windows_agent_present_ssh",
    "validate_host",
    "validate_password_file",
    "validate_ssh_user",
    "wait_for_agent_online",
]
