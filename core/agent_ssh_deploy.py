#!/usr/bin/env python3
"""Remote Agent bootstrap over OpenSSH.

SSH is used only for first-install bootstrap. Linux and Windows share the
transport, while keeping platform-specific preflight and bootstrap commands.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import stat
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
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
    combined = "\n".join(part for part in (result.stderr, result.stdout) if part).strip()
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

    lines = combined.splitlines()
    return lines[-1] if lines else fallback


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
        raise AgentDeployError(
            f"SSH preflight failed (Linux, curl, bash, python3 and {requirement} "
            f"are required): {_reason(result, 'remote preflight failed')}"
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
    return (
        _run_ssh(
            options,
            "test -f /var/lib/capivara-agent/identity.json -o -f /etc/capivara-agent/agent.conf",
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
